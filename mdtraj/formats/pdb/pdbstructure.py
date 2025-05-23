##############################################################################
# MDTraj: A Python Library for Loading, Saving, and Manipulating
#         Molecular Dynamics Trajectories.
# Copyright 2012-2013 Stanford University and the Authors
#
# Authors: Christopher M. Bruns
# Contributors: Peter Eastman, Robert McGibbon
#
# MDTraj is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 2.1
# of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with MDTraj. If not, see <http://www.gnu.org/licenses/>.
#
# Portions of this code originate from the OpenMM molecular simulation toolkit,
# copyright (c) 2012 Stanford University, Christopher M. Bruns and Peter Eastman,
# and are distributed under the following terms:
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS, CONTRIBUTORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
# USE OR OTHER DEALINGS IN THE SOFTWARE.
##############################################################################


import sys
import warnings

import numpy as np

from mdtraj.core import element


def _overflow_residue_check(num_str, pdbstructure, curr_atom):
    """
    Function to check and guess what the current residue is because it's overflowed. Lifted
    from a previous commit (c724024).

    Parameters
    ----------
    num_str : str
        str to be converted to int. Represents the residue number.
    pdbstructure : PdbStructure
        The PdbStructure object associated with `num_str`.
    curr_atom : Atom
        The current Atom object the residue number is associated with.

    Returns
    -------
    int
        The residue number deciphered in base 10.
    """
    if (
        pdbstructure._current_model is None
        or pdbstructure._current_model._current_chain is None
        or pdbstructure._current_model._current_chain._current_residue is None
    ):
        # This is the first residue in the model.
        return pdbstructure._next_residue_number
    else:
        currentRes = pdbstructure._current_model._current_chain._current_residue
        if currentRes.name_with_spaces != curr_atom.residue_name_with_spaces:
            # The residue name has changed.
            return pdbstructure._next_residue_number
        elif curr_atom.name_with_spaces in currentRes.atoms_by_name:
            # There is already an atom with this name.
            return pdbstructure._next_residue_number
        else:
            return currentRes.number


_atom_num_initial_nondecimal_functions = {
    "186a0": (lambda s, y=None: int(s, base=16)),  # "hex"
    "A0000": (lambda s, y=None: (int(s[0], base=36) * 10**4 + int(s[1:], base=36))),  # "chimera"
    "*****": (lambda s, y: y._next_atom_number),  # "overflow", y is the PdbStructure
}

_residue_num_initial_nondecimal_functions = {
    "2710": (lambda s, y=None, z=None: int(s, base=16)),  # 'hex'
    "A000": (lambda s, y=None, z=None: (int(s[0], base=36) * 10**3 + int(s[1:], base=36))),  # 'chimera'
    "****": _overflow_residue_check,  # 'overflow'
}


def _check_overflow_eligibility(num_str, str_type="atom"):
    """
    Return True if it's an overflow type, else False.

    An overflow type is defined as any dictionary keys above or
    something that looks the chimera format ({A..Z}000). The
    latter check exists because if residue numbers or atom numbers skip
    around and doesn't contain the start key, it might actually
    not recognize the overflow. This only exists for chimera-type values
    because it has no chance of false negatives.

    Parameters
    ----------
    num_str : str
        str to be checked whether it's overflowed or not.
    str_type : str, default: 'atom'
        The type of num_str. 'atom' if it's for an atom number,
        'residue' if it's for a residue number.

    Returns
    -------
    bool
        True if overflow type, False if not.
    """
    # Check a different dictionary depending on the type.
    if str_type == "atom":
        if num_str in _atom_num_initial_nondecimal_functions:
            return True
    elif str_type == "residue":
        if num_str in _residue_num_initial_nondecimal_functions:
            return True

    # This is mostly to 'guess' if the number is a chimera-type overflow, in case we skipped
    if 65 <= ord(num_str[0]) <= 90:
        # ord({A..Z}) should be in [65..90]
        return True
    else:
        return False


def _read_atom_number(num_str, pdbstructure=None):
    """
    This function determines whether we need to swap to overflow mode. Otherwise, we'll just
    turn ``num_str`` into an integer.

    If it's in any of the non-decimal modes, we will attempt to set the _atom_num_nondec_mode to the
    correct key. With this set, all subsequent atom numbers will be deciphered using a corresponding
    function.

    Parameters
    ----------
    num_str : str
        str to be converted to int. Represents the atom number.
    pdbstructure : PdbStructure, default: None
        The PdbStructure object associated with `num_str`.

    Returns
    -------
    int
        The atom number deciphered in base 10.
    """
    try:
        if pdbstructure._atom_num_nondec_mode is not None:
            # If it already has an overflow function, then it will use the corresponding
            # _atom_num_function as dictated by pdbstructure._atom_num_nondec_mode to decipher the num_str.
            return pdbstructure._atom_num_nondec_mode(num_str, pdbstructure)
        elif pdbstructure._next_atom_number > 99999 and _check_overflow_eligibility(num_str, "atom"):
            # If the next atom number is > 99999 and our current atom number is one of the overflow keys,
            # raise an OverflowError, which will switch to the correct mode to read num_str.
            raise OverflowError("Need to parse atom number using non-decimal residue modes.")
        else:
            return int(num_str)
    except (AttributeError, ValueError, OverflowError, KeyError):
        # we need to figure out on the 1st try which mode to switch to. There are currently 3
        # options: VMD (hex), Chimera (their own 'hybrid36' mode), and overflow (*****).
        # Chimera starts with A0000, vmd with 186a0, so they are distinguishable.
        if pdbstructure is None:
            try:
                return int(num_str)
            except ValueError:
                # num_str is not decimal, no nondec_mode to interpret it, no pdbstructure to say
                # what it is or to provide current number of atoms. No way to figure out
                return 0
        else:
            if pdbstructure._atom_num_nondec_mode is None:
                try:
                    # If this is the first time we reached overflow, we will try to determine the mode
                    # using the num_str as key.
                    pdbstructure._atom_num_nondec_mode = _atom_num_initial_nondecimal_functions[num_str]
                except KeyError:
                    if 65 <= ord(num_str[0]) <= 90:
                        # Could be a chimera-type overflow? Attempting to guess with that assumption.
                        pdbstructure._atom_num_nondec_mode = _atom_num_initial_nondecimal_functions["A0000"]
            try:
                # The _atom_num_nondec_mode has been set.
                # Try and run the corresponding _atom_num_functions on num_str
                return pdbstructure._atom_num_nondec_mode(num_str, pdbstructure)
            except (ValueError, KeyError, TypeError):
                # Didn't work, we need to change to overflow mode and guess with _next_atom_number.
                pdbstructure._atom_num_nondec_mode = _atom_num_initial_nondecimal_functions["*****"]
                warnings.warn(
                    f"Need to guess atom number {num_str} starting from atom {pdbstructure._next_atom_number}.",
                )
                return pdbstructure._atom_num_nondec_mode(num_str, pdbstructure)


def _read_residue_number(num_str, pdbstructure=None, curr_atom=None):
    """
    This function determines whether we need to swap to overflow mode. Otherwise, we'll just
    turn ``num_str`` into an integer.

    If it's in any of the non-decimal modes, we will attempt to set the _residue_num_nondec_mode to the
    correct key. With this set, all subsequent residue numbers will be deciphered using a corresponding
    function. If it's in "overflow" mode, will try to guess the residue number.

    Parameters
    ----------
    num_str : str
        str to be converted to int. Represents the residue number.
    pdbstructure : PdbStructure, default: None
        The PdbStructure object associated with `num_str`.
    curr_atom : Atom, default: None
        The current Atom object the residue number is associated with.

    Returns
    -------
    int
        The residue number deciphered in base 10.
    """
    try:
        if pdbstructure._residue_num_nondec_mode is not None:
            # If it already has an overflow function, then it will use the corresponding _residue_num_function
            # as dictated by pdbstructure._residue_num_nondec_mode to decipher the num_str.
            return pdbstructure._residue_num_nondec_mode(num_str, pdbstructure, curr_atom)
        elif pdbstructure._next_residue_number > 9999 and _check_overflow_eligibility(num_str, "residue"):
            # If the next residue number is > 9999 and our current residue number is one of the nondecimal keys,
            # Raise an OverflowError, which will switch to the correct mode to read num_str.
            raise OverflowError("Need to parse residue number using non-decimal residue modes.")
        else:
            return int(num_str)
    except (AttributeError, OverflowError, KeyError, ValueError):
        # we need to figure out on the 1st try which mode to switch to. There are currently 3 options:
        # VMD (hex) and Chimera (their own 'hybrid36' mode) and Overflow (****).
        # Chimera starts with A000, vmd with 2710, and Overflow just shows ****.
        # The can be turned into decimal with "int()" so the "hex" mode will only be
        # activated when _next_residue_number > 9999 (maximum in decimal) and current num_str
        # isn't 9999.
        if pdbstructure is None:
            try:
                return int(num_str)
            except ValueError:
                # num_str is not decimal, no pdbstructure to say what it is or
                # to provide current number of atoms. No way to figure out
                return 0
        else:
            if pdbstructure._residue_num_nondec_mode is None:
                # Attempt to set overflow mode using num_str as key
                try:
                    pdbstructure._residue_num_nondec_mode = _residue_num_initial_nondecimal_functions[num_str]
                except KeyError:
                    if 65 <= ord(num_str[0]) <= 90:
                        # Could be a chimera-type overflow? Attempting to guess with that assumption.
                        pdbstructure._residue_num_nondec_mode = _residue_num_initial_nondecimal_functions["A000"]
            try:
                # Try and run the _residue_num_functions
                return pdbstructure._residue_num_nondec_mode(num_str, pdbstructure, curr_atom)
            except (ValueError, KeyError, TypeError):
                # Didn't work, we need to change to overflow mode and guess with _next_residue_number
                pdbstructure._residue_num_nondec_mode = _residue_num_initial_nondecimal_functions["****"]
                warnings.warn(
                    f"Need to guess residue number string {num_str} starting from "
                    f"residue{pdbstructure._next_residue_number}, atom "
                    f"{pdbstructure._next_atom_number}.",
                )
                return pdbstructure._residue_num_nondec_mode(num_str, pdbstructure, curr_atom)


class PdbStructure:
    """
    PdbStructure object holds a parsed Protein Data Bank format file.

    Examples:

    Load a pdb structure from a file:
    > pdb = PdbStructure(open("1ARJ.pdb"))

    Fetch the first atom of the structure:
    > print(pdb.iter_atoms().next())
    ATOM      1  O5'   G N  17      13.768  -8.431  11.865  1.00  0.00           O

    Loop over all of the atoms of the structure
    > for atom in pdb.iter_atoms():
    >     print(atom)
    ATOM      1  O5'   G N  17      13.768  -8.431  11.865  1.00  0.00           O
    ...

    Get a list of all atoms in the structure:
    > atoms = list(pdb.iter_atoms())

    also:
    residues = list(pdb.iter_residues())
    positions = list(pdb.iter_positions())
    chains = list(pdb.iter_chains())
    models = list(pdb.iter_models())

    Fetch atomic coordinates of first atom:
    > print(pdb.iter_positions().next())
    [13.768, -8.431, 11.865]

     or

    > print(pdb.iter_atoms().next().position)
    [13.768, -8.431, 11.865]

    Strip the length units from an atomic position:
    > pos = pdb.iter_positions().next()
    > print(pos)
    [13.768, -8.431, 11.865]
    > print(pos)
    [13.768, -8.431, 11.865]
    > print(pos)
    [1.3768, -0.8431, 1.1865]


    The hierarchical structure of the parsed PDB structure is as follows:
    PdbStructure
      Model
        Chain
          Residue
            Atom
              Location

    Model - A PDB structure consists of one or more Models.  Each model corresponds to one version of
    an NMR structure, or to one frame of a molecular dynamics trajectory.

    Chain - A Model contains one or more Chains.  Each chain corresponds to one molecule, although multiple
    water molecules are frequently included in the same chain.

    Residue - A Chain contains one or more Residues.  One Residue corresponds to one of the repeating
    unit that constitutes a polymer such as protein or DNA.  For non-polymeric molecules, one Residue
    represents one molecule.

    Atom - A Residue contains one or more Atoms.  Atoms are chemical atoms.

    Location - An atom can sometimes have more that one position, due to static disorder in X-ray
    crystal structures.  To see all of the atom positions, use the atom.iter_positions() method,
    or pass the parameter "include_alt_loc=True" to one of the other iter_positions() methods.

    > for pos in pdb.iter_positions(include_alt_loc=True):
    >   ...

    Will loop over all atom positions, including multiple alternate locations for atoms that have
    multiple positions.  The default value of include_alt_loc is False for the iter_positions()
    methods.
    """

    def __init__(self, input_stream, load_all_models=True):
        """Create a PDB model from a PDB file stream.

        Parameters:
         - self (PdbStructure) The new object that is created.
         - input_stream (stream) An input file stream, probably created with
             open().
         - load_all_models (bool) Whether to load every model of an NMR
             structure or trajectory, or just load the first model, to save memory.
        """
        self._atom_num_nondec_mode = None  # None (decimal until changes), 'hex', 'chimera', 'overflow'
        self._residue_num_nondec_mode = None  # None (decimal until changes), 'hex', 'chimera', 'overflow'

        # initialize models
        self.load_all_models = load_all_models
        self.models = []
        self._current_model = None
        self.default_model = None
        self.models_by_number = {}
        self._unit_cell_lengths = None
        self._unit_cell_angles = None
        # read file
        self._load(input_stream)

    def _load(self, input_stream):
        state = None

        self._reset_atom_numbers()
        self._reset_residue_numbers()

        # Read one line at a time
        for pdb_line in input_stream:
            # Look for atoms
            if (pdb_line.find("ATOM  ") == 0) or (pdb_line.find("HETATM") == 0):
                if state == "NEW_MODEL":
                    new_number = self._current_model.number + 1
                    self._add_model(Model(new_number))
                    state = None
                self._add_atom(Atom(pdb_line, self))
            # Notice MODEL punctuation, for the next level of detail
            # in the structure->model->chain->residue->atom->position hierarchy
            elif pdb_line.find("MODEL") == 0:
                # model_number = int(pdb_line[10:14])
                if self._current_model is None:
                    new_number = 0
                else:
                    new_number = self._current_model.number + 1
                self._add_model(Model(new_number))
                self._reset_atom_numbers()
                self._reset_residue_numbers()
                state = None

            elif pdb_line.find("ENDMDL") == 0:
                self._current_model._finalize()
                if self.load_all_models:
                    state = "NEW_MODEL"
                else:
                    break

            elif pdb_line.find("END") == 0:
                self._current_model._finalize()
                if self.load_all_models:
                    state = "NEW_MODEL"
                else:
                    break

            elif pdb_line.find("TER") == 0 and pdb_line.split()[0] == "TER":
                self._current_model._current_chain._add_ter_record()
                self._reset_residue_numbers()

            elif pdb_line.find("CRYST1") == 0:
                self._unit_cell_lengths = (
                    float(pdb_line[6:15]),
                    float(pdb_line[15:24]),
                    float(pdb_line[24:33]),
                )
                self._unit_cell_angles = (
                    float(pdb_line[33:40]),
                    float(pdb_line[40:47]),
                    float(pdb_line[47:54]),
                )

            elif pdb_line.find("CONECT") == 0:
                atoms = []
                # :-1 to remove '\n' in the end so rstrip can work, -5 to leave space for +5 in the 'pos : pos+5'
                ll = len(pdb_line[:-1].rstrip(" ")) - 5

                for pos in [p for p in [6, 11, 16, 21, 26] if (p <= ll)]:
                    atoms.append(_read_atom_number(pdb_line[pos : pos + 5], pdbstructure=self))

                self._current_model.connects.append(atoms)

        self._finalize()

    def _reset_atom_numbers(self):
        self._atom_num_nondec_mode = None  # None (decimal until changes), 'hex', 'chimera', 'overflow'
        self._next_atom_number = 1

    def _reset_residue_numbers(self):
        self._residue_num_nondec_mode = None  # None (decimal until changes), 'hex', 'chimera', 'overflow'
        self._next_residue_number = 1

    def write(self, output_stream=sys.stdout):
        """Write out structure in PDB format"""
        for model in self.models:
            if len(model.chains) == 0:
                continue
            if len(self.models) > 1:
                print("MODEL     %4d" % model.number, file=output_stream)
            model.write(output_stream)
            if len(self.models) > 1:
                print("ENDMDL", file=output_stream)
        print("END", file=output_stream)

    def _add_model(self, model):
        if self.default_model is None:
            self.default_model = model
        self.models.append(model)
        self._current_model = model
        if model.number not in self.models_by_number:
            self.models_by_number[model.number] = model

    def get_model(self, model_number):
        return self.models_by_number[model_number]

    def model_numbers(self):
        return list(self.models_by_number.keys())

    def __contains__(self, model_number):
        return self.models_by_number.__contains__(model_number)

    def __getitem__(self, model_number):
        return self.models_by_number[model_number]

    def __iter__(self):
        yield from self.models

    def iter_models(self, use_all_models=False):
        if use_all_models:
            yield from self
        elif len(self.models) > 0:
            yield self.models[0]

    def iter_chains(self, use_all_models=False):
        for model in self.iter_models(use_all_models):
            yield from model.iter_chains()

    def iter_residues(self, use_all_models=False):
        for model in self.iter_models(use_all_models):
            yield from model.iter_residues()

    def iter_atoms(self, use_all_models=False):
        for model in self.iter_models(use_all_models):
            yield from model.iter_atoms()

    def iter_positions(self, use_all_models=False, include_alt_loc=False):
        """
        Iterate over atomic positions.

        Parameters
         - use_all_models (bool=False) Get positions from all models or just the first one.
         - include_alt_loc (bool=False) Get all positions for each atom, or just the first one.
        """
        for model in self.iter_models(use_all_models):
            yield from model.iter_positions(include_alt_loc)

    def __len__(self):
        return len(self.models)

    def _add_atom(self, atom):
        """ """
        if self._current_model is None:
            self._add_model(Model(0))
        atom.model_number = self._current_model.number
        # Atom might be alternate position for existing atom
        self._current_model._add_atom(atom)

    def _finalize(self):
        """Establish first and last residues, atoms, etc."""
        for model in self.models:
            model._finalize()

    def get_unit_cell_lengths(self):
        """Get the lengths of the crystallographic unit cell (may be None)."""
        return self._unit_cell_lengths

    def get_unit_cell_angles(self):
        """Get the angles of the crystallographic unit cell (may be None)."""
        return self._unit_cell_angles


class Model:
    """Model holds one model of a PDB structure.

    NMR structures usually have multiple models.  This represents one
    of them.
    """

    def __init__(self, model_number=1):
        self.number = model_number
        self.chains = []
        self._current_chain = None
        self.chains_by_id = {}
        self.connects = []

    def _add_atom(self, atom):
        """ """
        if len(self.chains) == 0:
            self._add_chain(Chain(atom.chain_id))
        # Create a new chain if the chain id has changed
        if self._current_chain.chain_id != atom.chain_id:
            self._add_chain(Chain(atom.chain_id))
        # Create a new chain after TER record, even if ID is the same
        elif self._current_chain.has_ter_record:
            self._add_chain(Chain(atom.chain_id))
        self._current_chain._add_atom(atom)

    def _add_chain(self, chain):
        self.chains.append(chain)
        self._current_chain = chain
        if chain.chain_id not in self.chains_by_id:
            self.chains_by_id[chain.chain_id] = chain

    def get_chain(self, chain_id):
        return self.chains_by_id[chain_id]

    def chain_ids(self):
        return list(self.chains_by_id.keys())

    def __contains__(self, chain_id):
        return self.chains_by_id.__contains__(chain_id)

    def __getitem__(self, chain_id):
        return self.chains_by_id[chain_id]

    def __iter__(self):
        return iter(self.chains)

    def iter_chains(self):
        yield from self

    def iter_residues(self):
        for chain in self:
            yield from chain.iter_residues()

    def iter_atoms(self):
        for chain in self:
            yield from chain.iter_atoms()

    def iter_positions(self, include_alt_loc=False):
        for chain in self:
            yield from chain.iter_positions(include_alt_loc)

    def __len__(self):
        return len(self.chains)

    def write(self, output_stream=sys.stdout):
        # Start atom serial numbers at 1
        sn = Model.AtomSerialNumber(1)
        for chain in self.chains:
            chain.write(sn, output_stream)

    def _finalize(self):
        for chain in self.chains:
            chain._finalize()

    class AtomSerialNumber:
        """pdb.Model inner class for pass-by-reference incrementable serial number"""

        def __init__(self, val):
            self.val = val

        def increment(self):
            self.val += 1


class Chain:
    def __init__(self, chain_id=" "):
        self.chain_id = chain_id
        self.residues = []
        self.has_ter_record = False
        self._current_residue = None
        self.residues_by_num_icode = {}
        self.residues_by_number = {}

    def _add_atom(self, atom):
        """ """
        # Create a residue if none have been created
        if len(self.residues) == 0:
            self._add_residue(
                Residue(
                    atom.residue_name_with_spaces,
                    atom.residue_number,
                    atom.insertion_code,
                    atom.alternate_location_indicator,
                    atom.segment_id,
                ),
            )
        # Create a residue if the residue information has changed
        elif self._current_residue.number != atom.residue_number:
            self._add_residue(
                Residue(
                    atom.residue_name_with_spaces,
                    atom.residue_number,
                    atom.insertion_code,
                    atom.alternate_location_indicator,
                    atom.segment_id,
                ),
            )
        elif self._current_residue.insertion_code != atom.insertion_code:
            self._add_residue(
                Residue(
                    atom.residue_name_with_spaces,
                    atom.residue_number,
                    atom.insertion_code,
                    atom.alternate_location_indicator,
                    atom.segment_id,
                ),
            )
        elif self._current_residue.name_with_spaces == atom.residue_name_with_spaces:
            # This is a normal case: number, name, and iCode have not changed
            pass
        elif atom.alternate_location_indicator != " ":
            # OK - this is a point mutation, Residue._add_atom will know what to do
            pass
        else:  # Residue name does not match
            # Only residue name does not match
            warnings.warn(
                f"WARNING: two consecutive residues with same number ({atom}, {self._current_residue.atoms[-1]})",
            )
            self._add_residue(
                Residue(
                    atom.residue_name_with_spaces,
                    atom.residue_number,
                    atom.insertion_code,
                    atom.alternate_location_indicator,
                    atom.segment_id,
                ),
            )
        self._current_residue._add_atom(atom)

    def _add_residue(self, residue):
        if len(self.residues) == 0:
            residue.is_first_in_chain = True
        self.residues.append(residue)
        self._current_residue = residue
        key = str(residue.number) + residue.insertion_code
        # only store the first residue with a particular key
        if key not in self.residues_by_num_icode:
            self.residues_by_num_icode[key] = residue
        if residue.number not in self.residues_by_number:
            self.residues_by_number[residue.number] = residue

    def write(self, next_serial_number, output_stream=sys.stdout):
        for residue in self.residues:
            residue.write(next_serial_number, output_stream)
        if self.has_ter_record:
            r = self.residues[-1]
            print(
                "TER   %5d      %3s %1s%4d%1s"
                % (
                    next_serial_number.val,
                    r.name_with_spaces,
                    self.chain_id,
                    r.number % 10000,
                    r.insertion_code,
                ),
                file=output_stream,
            )
            next_serial_number.increment()

    def _add_ter_record(self):
        self.has_ter_record = True
        self._finalize()

    def get_residue(self, residue_number, insertion_code=" "):
        return self.residues_by_num_icode[str(residue_number) + insertion_code]

    def __contains__(self, residue_number):
        return self.residues_by_number.__contains__(residue_number)

    def __getitem__(self, residue_number):
        """Returns the FIRST residue in this chain with a particular residue number"""
        return self.residues_by_number[residue_number]

    def __iter__(self):
        yield from self.residues

    def iter_residues(self):
        yield from self

    def iter_atoms(self):
        for res in self:
            yield from res

    def iter_positions(self, include_alt_loc=False):
        for res in self:
            yield from res.iter_positions(include_alt_loc)

    def __len__(self):
        return len(self.residues)

    def _finalize(self):
        self.residues[0].is_first_in_chain = True
        self.residues[-1].is_final_in_chain = True
        for residue in self.residues:
            residue._finalize()


class Residue:
    def __init__(
        self,
        name,
        number,
        insertion_code=" ",
        primary_alternate_location_indicator=" ",
        segment_id="",
    ):
        alt_loc = primary_alternate_location_indicator
        self.primary_location_id = alt_loc
        self.segment_id = segment_id
        self.locations = {}
        self.locations[alt_loc] = Residue.Location(alt_loc, name)
        self.name_with_spaces = name
        self.number = number
        self.insertion_code = insertion_code
        self.atoms = []
        self.atoms_by_name = {}
        self.is_first_in_chain = False
        self.is_final_in_chain = False
        self._current_atom = None

    def _add_atom(self, atom):
        """ """
        alt_loc = atom.alternate_location_indicator
        if alt_loc not in self.locations:
            self.locations[alt_loc] = Residue.Location(
                alt_loc,
                atom.residue_name_with_spaces,
            )
        assert atom.residue_number == self.number
        assert atom.insertion_code == self.insertion_code

        # Check whether this is an existing atom with another position
        if atom.name_with_spaces in self.atoms_by_name:
            old_atom = self.atoms_by_name[atom.name_with_spaces]
            # Unless this is a duplicated atom (warn about file error)
            if atom.alternate_location_indicator in old_atom.locations:
                pass  # TJL COMMENTED OUT
                # warnings.warn(
                #   "WARNING: duplicate atom (%s, %s)" % (
                #       atom,
                #       old_atom._pdb_string(old_atom.serial_number, atom.alternate_location_indicator),
                #   )
                # )
            else:
                for alt_loc, position in atom.locations.items():
                    old_atom.locations[alt_loc] = position
                return  # no new atom added

        # actually use new atom
        self.atoms_by_name[atom.name] = atom
        self.atoms_by_name[atom.name_with_spaces] = atom
        self.atoms.append(atom)
        self._current_atom = atom

    def write(self, next_serial_number, output_stream=sys.stdout, alt_loc="*"):
        for atom in self.atoms:
            atom.write(next_serial_number, output_stream, alt_loc)

    def _finalize(self):
        if len(self.atoms) > 0:
            self.atoms[0].is_first_atom_in_chain = self.is_first_in_chain
            self.atoms[-1].is_final_atom_in_chain = self.is_final_in_chain
            for atom in self.atoms:
                atom.is_first_residue_in_chain = self.is_first_in_chain
                atom.is_final_residue_in_chain = self.is_final_in_chain

    def set_name_with_spaces(self, name, alt_loc=None):
        # Gromacs ffamber PDB files can have 4-character residue names
        # assert len(name) == 3
        if alt_loc is None:
            alt_loc = self.primary_location_id
        loc = self.locations[alt_loc]
        loc.name_with_spaces = name
        loc.name = name.strip()

    def get_name_with_spaces(self, alt_loc=None):
        if alt_loc is None:
            alt_loc = self.primary_location_id
        loc = self.locations[alt_loc]
        return loc.name_with_spaces

    name_with_spaces = property(
        get_name_with_spaces,
        set_name_with_spaces,
        doc="four-character residue name including spaces",
    )

    def get_name(self, alt_loc=None):
        if alt_loc is None:
            alt_loc = self.primary_location_id
        loc = self.locations[alt_loc]
        return loc.name

    name = property(get_name, doc="residue name")

    def get_atom(self, atom_name):
        return self.atoms_by_name[atom_name]

    def __contains__(self, atom_name):
        return self.atoms_by_name.__contains__(atom_name)

    def __getitem__(self, atom_name):
        """Returns the FIRST atom in this residue with a particular atom name"""
        return self.atoms_by_name[atom_name]

    def __iter__(self):
        "Iterator over atoms"
        yield from self.iter_atoms()

    # Three possibilities: primary alt_loc, certain alt_loc, or all alt_locs
    def iter_atoms(self, alt_loc=None):
        if alt_loc is None:
            locs = [self.primary_location_id]
        elif alt_loc == "":
            locs = [self.primary_location_id]
        elif alt_loc == "*":
            locs = None
        else:
            locs = list(alt_loc)
        # If an atom has any location in alt_loc, emit the atom
        for atom in self.atoms:
            use_atom = False  # start pessimistic
            for loc2 in atom.locations.keys():
                if locs is None:  # means all locations
                    use_atom = True
                elif loc2 in locs:
                    use_atom = True
            if use_atom:
                yield atom

    def iter_positions(self, include_alt_loc=False):
        """Returns one position per atom, even if an individual atom has multiple positions."""
        for atom in self:
            if include_alt_loc:
                yield from atom.iter_positions()
            else:
                yield atom.position

    def __len__(self):
        return len(self.atoms)

    # Residues can have multiple locations, based on alt_loc indicator
    class Location:
        """
        Inner class of residue to allow different residue names for different alternate_locations.
        """

        def __init__(self, alternate_location_indicator, residue_name_with_spaces):
            self.alternate_location_indicator = alternate_location_indicator
            self.residue_name_with_spaces = residue_name_with_spaces


class Atom:
    """Atom represents one atom in a PDB structure."""

    def __init__(self, pdb_line, pdbstructure=None):
        """Create a new pdb.Atom from an ATOM or HETATM line.

        Example line:
        ATOM   2209  CB  TYR A 299       6.167  22.607  20.046  1.00  8.12           C
        00000000011111111112222222222333333333344444444445555555555666666666677777777778
        12345678901234567890123456789012345678901234567890123456789012345678901234567890

        ATOM line format description from
          http://deposit.rcsb.org/adit/docs/pdb_atom_format.html:

        COLUMNS        DATA TYPE       CONTENTS
        --------------------------------------------------------------------------------
         1 -  6        Record name     "ATOM  "
         7 - 11        Integer         Atom serial number.
        13 - 16        Atom            Atom name.
        17             Character       Alternate location indicator.
        18 - 20        Residue name    Residue name.
        22             Character       Chain identifier.
        23 - 26        Integer         Residue sequence number.
        27             AChar           Code for insertion of residues.
        31 - 38        Real(8.3)       Orthogonal coordinates for X in Angstroms.
        39 - 46        Real(8.3)       Orthogonal coordinates for Y in Angstroms.
        47 - 54        Real(8.3)       Orthogonal coordinates for Z in Angstroms.
        55 - 60        Real(6.2)       Occupancy (Default = 1.0).
        61 - 66        Real(6.2)       Temperature factor (Default = 0.0).
        73 - 76        LString(4)      Segment identifier, left-justified.
        77 - 78        LString(2)      Element symbol, right-justified.
        79 - 80        LString(2)      Charge on the atom.

        """
        # We might modify first/final status during _finalize() methods
        self.is_first_atom_in_chain = False
        self.is_final_atom_in_chain = False
        self.is_first_residue_in_chain = False
        self.is_final_residue_in_chain = False
        # Start parsing fields from pdb line
        self.record_name = pdb_line[0:6].strip()

        self.serial_number = _read_atom_number(pdb_line[6:11], pdbstructure=pdbstructure)

        self.name_with_spaces = pdb_line[12:16]
        alternate_location_indicator = pdb_line[16]

        self.residue_name_with_spaces = pdb_line[17:20]
        # In some MD codes, notably ffamber in gromacs, residue name has a fourth character in
        # column 21
        possible_fourth_character = pdb_line[20:21]
        if possible_fourth_character != " ":
            # Fourth character should only be there if official 3 are already full
            if len(self.residue_name_with_spaces.strip()) != 3:
                raise ValueError("Misaligned residue name: %s" % pdb_line)
            self.residue_name_with_spaces += possible_fourth_character
        self.residue_name = self.residue_name_with_spaces.strip()

        self.chain_id = pdb_line[21]
        self.residue_number = _read_residue_number(pdb_line[22:26], pdbstructure, self)

        self.insertion_code = pdb_line[26]
        # coordinates, occupancy, and temperature factor belong in Atom.Location object
        x = float(pdb_line[30:38])
        y = float(pdb_line[38:46])
        z = float(pdb_line[46:54])
        try:
            occupancy = float(pdb_line[54:60])
        except ValueError:
            occupancy = 1.0
        try:
            temperature_factor = float(pdb_line[60:66])
        except ValueError:
            temperature_factor = 0.0
        self.locations = {}
        loc = Atom.Location(
            alternate_location_indicator,
            np.array([x, y, z]),
            occupancy,
            temperature_factor,
            self.residue_name_with_spaces,
        )
        self.locations[alternate_location_indicator] = loc
        self.default_location_id = alternate_location_indicator
        # segment id, element_symbol, and formal_charge are not always present
        self.segment_id = pdb_line[72:76].strip()
        self.element_symbol = pdb_line[76:78].strip()

        # Handle charges
        self.formal_charge = None
        charge_string = pdb_line[78:80].strip()  # Is there any charge information?
        if charge_string:
            # A PDB charge string may either be of format
            # {charge}{sign} or {sign}{charge}
            # We should try both.
            try:
                # Try the string as is. This will work for {sign}{charge}
                self.formal_charge = int(charge_string)
            except ValueError:
                # Try reversing (other format)
                try:
                    charge_string = charge_string[::-1]
                    self.formal_charge = int(charge_string)
                except ValueError:
                    warnings.warn(f"Could not parse charge information for atom {self._pdb_string()}\nSetting to None")
        # figure out atom element
        try:
            # First try to find a sensible element symbol from columns 76-77
            self.element = element.get_by_symbol(self.element_symbol)
        except KeyError:
            # otherwise, deduce element from first two characters of atom name
            # remove digits found in some hydrogen atom names
            symbol = self.name_with_spaces[0:2].strip().lstrip("0123456789")
            try:
                # Some molecular dynamics PDB files, such as gromacs with ffamber force
                # field, include 4-character hydrogen atom names beginning with "H".
                # Hopefully elements like holmium (Ho) and mercury (Hg) will have fewer than four
                # characters in the atom name.  This problem is the fault of molecular
                # dynamics code authors who feel the need to make up their own atom
                # nomenclature because it is too tedious to read that provided by the PDB.
                # These are the same folks who invent their own meanings for biochemical terms
                # like "dipeptide".  Clowntards.
                if len(self.name) == 4 and self.name[0:1] == "H":
                    self.element = element.hydrogen
                else:
                    self.element = element.get_by_symbol(symbol)
            except KeyError:
                # OK, I give up
                self.element = None
        if pdbstructure is not None:
            pdbstructure._next_atom_number = self.serial_number + 1
            pdbstructure._next_residue_number = self.residue_number + 1

    def iter_locations(self):
        """
        Iterate over Atom.Location objects for this atom, including primary location.
        """
        for alt_loc in self.locations:
            yield self.locations[alt_loc]

    def iter_positions(self):
        """
        Iterate over atomic positions.  Returns Quantity(Vec3(), unit) objects, unlike
        iter_locations, which returns Atom.Location objects.
        """
        for loc in self.iter_locations():
            yield loc.position

    def iter_coordinates(self):
        """
        Iterate over x, y, z values of primary atom position.
        """
        yield from self.position

    # Hide existence of multiple alternate locations to avoid scaring casual users
    def get_location(self, location_id=None):
        id = location_id
        if id is None:
            id = self.default_location_id
        return self.locations[id]

    def set_location(self, new_location, location_id=None):
        id = location_id
        if id is None:
            id = self.default_location_id
        self.locations[id] = new_location

    location = property(get_location, set_location, doc="default Atom.Location object")

    def get_position(self):
        return self.location.position

    def set_position(self, coords):
        self.location.position = coords

    position = property(get_position, set_position, doc="orthogonal coordinates")

    def get_alternate_location_indicator(self):
        return self.location.alternate_location_indicator

    alternate_location_indicator = property(get_alternate_location_indicator)

    def get_occupancy(self):
        return self.location.occupancy

    occupancy = property(get_occupancy)

    def get_temperature_factor(self):
        return self.location.temperature_factor

    temperature_factor = property(get_temperature_factor)

    def get_x(self):
        return self.position[0]

    x = property(get_x)

    def get_y(self):
        return self.position[1]

    y = property(get_y)

    def get_z(self):
        return self.position[2]

    z = property(get_z)

    def _pdb_string(self, serial_number=None, alternate_location_indicator=None):
        """
        Produce a PDB line for this atom using a particular serial number and alternate location
        """
        if serial_number is None:
            serial_number = self.serial_number
        if alternate_location_indicator is None:
            alternate_location_indicator = self.alternate_location_indicator
        # produce PDB line in three parts: names, numbers, and end
        # Accomodate 4-character residue names that use column 21
        long_res_name = self.residue_name_with_spaces
        if len(long_res_name) == 3:
            long_res_name += " "
        assert len(long_res_name) == 4
        names = "%-6s%5d %4s%1s%4s%1s%4d%1s   " % (
            self.record_name,
            serial_number,
            self.name_with_spaces,
            alternate_location_indicator,
            long_res_name,
            self.chain_id,
            self.residue_number,
            self.insertion_code,
        )
        numbers = f"{self.x:8.3f}{self.y:8.3f}{self.z:8.3f}{self.occupancy:6.2f}{self.temperature_factor:6.2f}      "
        end = "%-4s%2s" % (
            self.segment_id,
            self.element_symbol,
        )
        formal_charge = "  "
        if self.formal_charge is not None:
            formal_charge = "%+2d" % self.formal_charge
        return names + numbers + end + formal_charge

    def __str__(self):
        return self._pdb_string(self.serial_number, self.alternate_location_indicator)

    def write(self, next_serial_number, output_stream=sys.stdout, alt_loc="*"):
        """
        alt_loc = "*" means write all alternate locations
        alt_loc = None means write just the primary location
        alt_loc = "AB" means write locations "A" and "B"
        """
        if alt_loc is None:
            locs = [self.default_location_id]
        elif alt_loc == "":
            locs = [self.default_location_id]
        elif alt_loc == "*":
            locs = self.locations.keys()
            locs.sort()
        else:
            locs = list(alt_loc)
        for loc_id in locs:
            print(self._pdb_string(next_serial_number.val, loc_id), file=output_stream)
            next_serial_number.increment()

    def set_name_with_spaces(self, name):
        assert len(name) == 4
        self._name_with_spaces = name
        self._name = name.strip()

    def get_name_with_spaces(self):
        return self._name_with_spaces

    name_with_spaces = property(
        get_name_with_spaces,
        set_name_with_spaces,
        doc="four-character residue name including spaces",
    )

    def get_name(self):
        return self._name

    name = property(get_name, doc="residue name")

    class Location:
        """
        Inner class of Atom for holding alternate locations
        """

        def __init__(
            self,
            alt_loc,
            position,
            occupancy,
            temperature_factor,
            residue_name,
        ):
            self.alternate_location_indicator = alt_loc
            self.position = position
            self.occupancy = occupancy
            self.temperature_factor = temperature_factor
            self.residue_name = residue_name

        def __iter__(self):
            yield from self.position

        def __str__(self):
            return str(self.position)
