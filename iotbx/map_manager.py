from __future__ import absolute_import, division, print_function
from libtbx.utils import to_str
from libtbx import group_args
import sys
import io
from cctbx import miller
from iotbx.mrcfile import map_reader, write_ccp4_map
from scitbx.array_family import flex
from cctbx import maptbx
from cctbx import miller
import mmtbx.ncs.ncs
from copy import deepcopy

class map_manager(map_reader, write_ccp4_map):

  '''
   map_manager, includes map_reader and write_ccp4_map

   This class is intended to be the principal mechanism for reading
   and writing map information.  It is intended to be used by the
   iotbx.data_manager for both of these purposes.

   Use map_manager to read, write, and carry information about
   one map.  Map_manager keeps track of the origin shifts and also the
   original full unit cell and cell dimensions.  It writes out the map
   in the same place as it was read in.

   Map_manager also keeps track of any changes in magnification. These
   are reflected in changes in unit_cell and crystal_symmetry cell dimensions
   and angles.

   You normally create a new map_manager by initializing map_manager with a
   file name.  Then you apply the shift_origin() method and the map is
   shifted to place the origin at (0, 0, 0) and the original origin is
   recorded as self.origin_shift_grid_units.

   You can also create a map_manager with a map_data object (3D flex.double()
   array) along with the meta-data below.

   NOTE: MRC Maps may not represent the entire unit cell.  Normally maps that
    have an origin (corner with minimum i, j, k) that is not zero will be
    shifted at a later stage to have the origin at (0, 0, 0), along with
    any models and ncs objects (typically done with iotbx.map_and_model).
    To be able to write out a map in the same place as it was read in
    after shifting the origin and/or boxing the map, you need to keep track
    of 3 things.  These are:
    1. unit_cell_grid: grid representing one full unit cell as read in.
        Saved in map_manager as self.unit_cell_grid
    2. unit_cell_crystal_symmetry: dimensions and space group of full unit cell
        Saved in map_manager as self._unit_cell_crystal_symmetry
    3. origin_shift_grid_units: the shift in grid units to apply to the
       working map to superimpose it on the original map. When you read the
       map in this is (0, 0, 0). If you shift the map origin from (i, j, k) to
       (0, 0, 0) then the origin_shift_grid_units is (i, j, k).
         Saved in map_manager as self.origin_shift_grid_units

   Magnification (pixel size scaling) of a map: there is no general parameter
   describing magnification of an MRC map.  Changes in scaling are
   recorded in map_manager as changes in the scaling matrix/translation that
   relates grid points in a map to real-space position.

   Normal usage (NOTE: read/write should normally be done through data_manager):

     Read in a map:
       mm = map_manager('input_map.mrc')
     Summarize:
       mm.show_summary()

     Normally shift origin of map to (0, 0, 0) (you can do this here
         or you can use iotbx.map_and_model to shift models and maps together):
       mm.shift_origin()

     Get the map_data (shifted if origin was shifted above):
       map_data = mm.map_data()

     Get the crystal_symmetry of the box of data that is present:
       cs = mm.crystal_symmetry()

     Get the crystal_symmetry of the whole unit cell (even if not present):
       unit_cell_cs = mm.unit_cell_crystal_symmetry()

     Write out the map in map_data() in original location:
       mm.write_map(file_name = 'output_map.ccp4')

   --------     CONVENTIONS  --------------
   See http://www.ccpem.ac.uk/mrc_format/mrc2014.php for MRC format
   See https://pypi.org/project/mrcfile/ for mrcfile library documentation

   Same conventions as iotbx.ccp4_map

   Default is to write maps with INTERNAL_STANDARD_ORDER of axes of [3, 2, 1]
     corresponding to columns in Z, rows in Y, sections in X to match
     flex array layout.  This can be modified by changing the values in
     output_axis_order.

   Hard-wired to convert input maps of any order to
     INTERNAL_STANDARD_ORDER = [3, 2, 1] before conversion to flex arrays
     This is not modifiable.

    INTERNAL_STANDARD_ORDER = [3, 2, 1]

  Standard limitations and associated message.
  These can be checked with: limitations = mrc.get_limitations()
    which returns a group_args object with a list of limitations and a list
    of corresponding error messages, or None if there are none
    see phenix.show_map_info for example
  These limitations can also be accessed with specific calls placed below:
   For example:
   mrc.can_be_sharpened()  returns False if "extract_unique" is present

  Map labels that are not limitations can be accessed with:
      additional_labels = mrc.get_additional_labels()

  STANDARD_LIMITATIONS_DICT = {
    "extract_unique":
     "This map is masked around unique region and not suitable for auto-sharpening.",
    "map_is_sharpened":
     "This map is auto-sharpened and not suitable for further auto-sharpening.",
    "map_is_density_modified": "This map has been density modified.",
     }


   NOTES ON ORDER OF AXES

    Phenix standard order is 3, 2, 1 (columns Z, rows Y, sections in X).
        Convert everything to this order.

    This is the order that allows direct conversion of a numpy 3D array
     with axis order (mapc, mapr, maps) to a flex array.

    For reverse = True, supply order that converts flex array to numpy 3D array
     with order (mapc, mapr, maps)

    Note that this does not mean input or output maps have to be in this order.
     It just means that before conversion of numpy to flex or vice-versa
     the array has to be in this order.

     Note that MRC standard order for input/ouput is 1, 2, 3.

     NOTE: numpy arrays indexed from 0 so this is equivalent to
      order of 2, 1, 0 in the numpy array

    NOTE:  MRC format allows data axes to be swapped using the header
      mapc mapr and maps fields. However the mrcfile library does not
      attempt to swap the axes and assigns the columns to X, rows to Y and
      sections to Z. The data array is indexed C-style, so data values can
      be accessed using mrc.data[z][y][x].

    NOTE: normal expectation is that phenix will read/write with the
      order 3, 2, 1. This means X-sections (index = 3), Y rows (index = 2),
      Z columns (index = 1). This correxponds to
       mapc (columns) =   3 or Z
       mapr (rows)    =   2 or Y
       maps (sections) =  1 or X

    In the numpy array (2, 1, 0 instead of 3, 2, 1):

    To transpose, specify i0, i1, i2 where:
        i0 = 2 means input axis 0 becomes output axis 2
        NOTE:  axes are 0, 1, 2 etc, not 1, 2, 3
      Examples:
        np.transpose(a, (0, 1, 2))  does nothing
        np.transpose(a, (1, 2, 0)) output axis 0 is input axis 1



    We want output axes to always be 2, 1, 0 and input axes for numpy array are
      (mapc-1, mapr-1, maps-1):

    For example, in typical phenix usage, the transposition is:
      i_mapc = 3    i_mapc_np = 2
      i_mapr = 2    i_mapr_np = 1
      i_maps = 1    i_maps_np = 0

   --------     END CONVENTIONS  --------------

  '''


  def __init__(self,
     file_name = None,  # USUAL: Initialize from file: No other information used
     map_data = None,   # OR map_data, unit_cell_grid, unit_cell_crystal_symmetry
     unit_cell_grid = None,
     unit_cell_crystal_symmetry = None,
     origin_shift_grid_units = None, # OPTIONAL first point in map in full cell
     ncs_object = None, # OPTIONAL ncs_object with map symmetry
     log = None,
     ):

    '''
      Allows reading a map file or initialization with map_data

      Normally call with file_name to read map file in CCP4/MRC format.

      Alternative is initialize with map_data and metadata
       Required: specify map_data, unit_cell_grid, unit_cell_crystal_symmetry
       Optional: specify origin_shift_grid_units

      Optional in either case: supply ncs_object with map symmetry of full map

      NOTE on "crystal_symmetry" objects
      There are two objects that are "crystal_symmetry" objects:
      A.  unit_cell_crystal_symmetry():  This is the symmetry of the
        entire unit cell. It can be any space group. The dimensions
        correspond to the dimensions of unit_cell_grid.

      B.  crystal_symmetry():  This is the symmetry of the part of the map
        that is present.  If the entire map is present, this can be any
        space group. Otherwise it is set to P 1 (no symmetry other than unity).
        The dimensions correspond to the dimensions of the map_data.all().

      NOTE: As of 2020-05-22 both map_reader and map_manager ALWAYS convert
      map_data to flex.double.

      Map_manager does not save any extra information about
      the map except the details specified in this __init__.

      After reading you can access map data with self.map_data()
        and other attributes (see class utils in ccp4_map/__init__py)
    '''

    assert (file_name is not None) or [map_data,unit_cell_grid,
        unit_cell_crystal_symmetry].count(None)==0

    assert (ncs_object is None) or isinstance(ncs_object, mmtbx.ncs.ncs.ncs)
    # Initialize log filestream
    self.set_log(log)


    # NOTE: If you add anything here to be initialized, add it to the
    #  customized_copy method

    # Initialize mask to be not present
    self._created_mask = None

    # Initialize program_name, limitations, labels
    self.input_file_name = file_name # input file (source of this manager)
    self.program_name = None  # Name of program using this manager
    self.limitations = None  # Limitations from STANDARD_LIMITATIONS_DICT
    self.labels = None  # List of labels (usually from input file) to be written

    # Initialze ncs_object
    self._ncs_object = ncs_object

    # Initialize origin shift representing position of original origin in
    #  grid units.  If map is shifted, this is updated to reflect where
    #  to place current origin to superimpose map on original map.

    # Usual initialization with a file

    if self.input_file_name is not None:
      self._read_map()
      # Sets self.unit_cell_grid, self._unit_cell_crystal_symmetry, self.data,
      #  self._crystal_symmetry.  Sets also self.external_origin

      # read_map does not set self.origin_shift_grid_units. Set them here:

      # Set starting values:
      self.origin_shift_grid_units = (0, 0, 0)

    else:
      '''
         Initialization with map_data object and metadata
      '''

      assert map_data and unit_cell_grid and unit_cell_crystal_symmetry

      # Required initialization information:
      self.data = map_data
      self.unit_cell_grid = unit_cell_grid
      self._unit_cell_crystal_symmetry = unit_cell_crystal_symmetry

      # Calculate values for self._crystal_symmetry
      # Must always run this method after changing
      #    self._unit_cell_crystal_symmetry  or self.unit_cell_grid
      self.set_crystal_symmetry_of_partial_map()

      # Optional initialization information
      if origin_shift_grid_units is None:
        origin_shift_grid_units = (0, 0, 0)
      self.origin_shift_grid_units = origin_shift_grid_units

    # Initialization steps always done:

    # make sure labels are strings
    if self.labels is not None:
      self.labels = [to_str(label, codec = 'utf8') for label in self.labels]

  # prevent pickling error in Python 3 with self.log = sys.stdout
  # unpickling is limited to restoring sys.stdout
  def __getstate__(self):
    pickle_dict = self.__dict__.copy()
    if isinstance(self.log, io.TextIOWrapper):
      pickle_dict['log'] = None
    return pickle_dict

  def __setstate__(self, pickle_dict):
    self.__dict__ = pickle_dict
    if self.log is None:
      self.log = sys.stdout

  def set_log(self, log = sys.stdout):
    '''
       Set output log file
    '''
    if log is None:
      self.log = sys.stdout
    else:
      self.log = log

  def _read_map(self):
      '''
       Read map using mrcfile/__init__.py
       Sets self.unit_cell_grid, self._unit_cell_crystal_symmetry, self.data
           self._crystal_symmetry
       Does not set self.origin_shift_grid_units
       Does set self.input_file_name
      '''
      self._print("Reading map from %s " %(self.input_file_name))

      self.read_map_file(file_name = self.input_file_name)  # mrcfile/__init__.py

  def _print(self, m):
    if (self.log is not None) and hasattr(self.log, 'closed') and (
        not self.log.closed):
      print(m, file = self.log)

  def set_unit_cell_crystal_symmetry(self, crystal_symmetry):
    '''
      Specify the dimensions and space group of unit cell.  This also changes
      the crystal_symmetry of the part that is present and the grid spacing.

      Purpose is to redefine the dimensions of the map without changing values
      of the map.  Normally used to correct the dimensions of a map
      where something was defined incorrectly.

      Does not change self.unit_cell_grid

       Fundamental parameters set:
        self._unit_cell_crystal_symmetry: dimensions of full unit cell
        self._crystal_symmetry: dimensions of part of unit cell that is present
    '''

    from cctbx import crystal
    assert isinstance(crystal_symmetry, crystal.symmetry)
    self._unit_cell_crystal_symmetry = crystal_symmetry

    # Always follow a set of _unit_cell_crystal_symmetry with this:
    self.set_crystal_symmetry_of_partial_map()

  def set_original_origin_and_gridding(self,
      original_origin = None,
      gridding = None):
    '''
       Specify the location in the full unit cell grid where the origin of
       the map that is present is to be placed to match its original position.
       This is referred to here as the "original" origin, as opposed to the
       current origin of this map.

       Note that this method does not actually shift the origin of the working
       map.  It just defines where that origin is going to be placed when
       restoring the map to its original position.

       Also optionally redefine the definition of the unit cell, keeping the
       grid spacing the same.

       This allows redefining the location of the map that is present
       within the full unit cell.  It also allows redefining the
       unit cell itself.  Only use this to create a new partial map
       in a defined location.

       Previous definition of the location of the map that is present
       is discarded.

       Fundamental parameters set:
        self.origin_shift_grid_units: shift to place origin in original location
        self._unit_cell_crystal_symmetry: dimensions of full unit cell
        self.unit_cell_grid: grid units of full unit cell
    '''

    if original_origin:
      if (self.origin_shift_grid_units !=  (0, 0, 0)) or (
          not self.origin_is_zero()):
        self.shift_origin()
        self._print("Previous origin shift of %s will be discarded" %(
          str(self.origin_shift_grid_units)))

      # Set the origin
      self.origin_shift_grid_units = original_origin
      self._print("New origin shift will be %s " %(
        str(self.origin_shift_grid_units)))

    if gridding: # reset definition of full unit cell.  Keep grid spacing
       current_unit_cell_parameters = self.unit_cell_crystal_symmetry(
            ).unit_cell().parameters()
       current_unit_cell_grid = self.unit_cell_grid
       new_unit_cell_parameters = []
       for a, g, new_g in zip(
          current_unit_cell_parameters[:3], current_unit_cell_grid, gridding):
         new_a = a*new_g/g
         new_unit_cell_parameters.append(new_a)

       unit_cell_parameters = \
          new_unit_cell_parameters+list(current_unit_cell_parameters[3:])
       from cctbx import crystal
       self._unit_cell_crystal_symmetry = crystal.symmetry(
          unit_cell_parameters,
          self._unit_cell_crystal_symmetry.space_group_number())

       self.unit_cell_grid = gridding
       if current_unit_cell_grid !=  gridding:
         self._print ("Resetting gridding of full unit cell from %s to %s" %(
           str(current_unit_cell_grid), str(gridding)))
         self._print ("Resetting dimensions of full unit cell from %s to %s" %(
           str(current_unit_cell_parameters),
            str(new_unit_cell_parameters)))

       # Always run after setting unit_cell_grid or _unit_cell_crystal_symmetry
       # This time it should not change anything
       original_crystal_symmetry = self.crystal_symmetry()
       self.set_crystal_symmetry_of_partial_map()
       new_crystal_symmetry = self.crystal_symmetry()
       assert original_crystal_symmetry.is_similar_symmetry(
         new_crystal_symmetry)

  def origin_is_zero(self):
    if self.map_data().origin() == (0, 0, 0):
      return True
    else:
      return False

  def shift_origin(self, desired_origin = (0, 0, 0)):
    '''
    Shift the origin of the map to desired_origin
        (normally desired_origin = (0, 0, 0) and update origin_shift_grid_units

    Origin is the value of self.map_data().origin()
    origin_shift_grid_units is the shift to apply to self.map_data() to
      superimpose it on the original map.

    If you shift the origin by (i, j, k) then add -(i, j, k) to
      the current origin_shift_grid_units.

    If current origin is at (a, b, c) and
       desired origin = (d, e, f) and
       existing origin_shift_grid_units is (g, h, i):

    the shift to make is  (d, e, f) - (a, b, c)

    the new value of origin_shift_grid_units will be:
       (g, h, i)+(a, b, c)-(d, e, f)
       or new origin_shift_grid_units is: (g, h, i)- shift

    the new origin of map_data will be (d, e, f)

    '''

    if(self.map_data() is None): return

    # Figure out what the shifts are (in grid units)
    shift_info = self._get_shift_info(desired_origin = desired_origin)

    # Update the value of origin_shift_grid_units
    #  This is position of the origin of the new map in the full unit cell grid
    self.origin_shift_grid_units = shift_info.new_origin_shift_grid_units

    # Shift map_data if necessary
    if shift_info.shift_to_apply !=  (0, 0, 0):
      # map will start at desired_origin and have current size:
      acc = flex.grid(shift_info.desired_origin, shift_info.new_end)
      self.map_data().reshape(acc)

    # Checks
    new_current_origin = self.map_data().origin()
    assert new_current_origin == shift_info.desired_origin

    assert add_tuples_int(shift_info.current_origin, shift_info.shift_to_apply
        ) == shift_info.desired_origin

    # Original location of first element of map should agree with previous

    assert shift_info.map_corner_original_location  ==  add_tuples_int(
       new_current_origin, self.origin_shift_grid_units)

    # If there is an associated ncs_object, shift it too
    if self.ncs_object():
      self.set_ncs_object_shift_cart_to_match_map(self.ncs_object())

  def _get_shift_info(self, desired_origin = None):
    '''
      Utility to calculate the shift necessary (grid units)
      map to place the origin of the current map
      at the position defined by desired_origin.
      See definitions in shift_origin method.

    '''
    if(desired_origin is None):
      desired_origin = (0, 0, 0)
    desired_origin = tuple(desired_origin)

    if(self.origin_shift_grid_units is None):
      self.origin_shift_grid_units = (0, 0, 0)

    # Current origin and shift to apply
    current_origin = self.map_data().origin()

    # Original location of first element of map
    map_corner_original_location = add_tuples_int(current_origin,
         self.origin_shift_grid_units)

    shift_to_apply = subtract_tuples_int(desired_origin, current_origin)

    assert add_tuples_int(current_origin, shift_to_apply) == desired_origin

    new_origin_shift_grid_units = subtract_tuples_int(
        self.origin_shift_grid_units, shift_to_apply)

    current_end = add_tuples_int(current_origin, self.map_data().all())
    new_end = add_tuples_int(desired_origin, self.map_data().all())

    shift_info = group_args(
      map_corner_original_location = map_corner_original_location,
      current_origin = current_origin,
      current_end = current_end,
      current_origin_shift_grid_units = self.origin_shift_grid_units,
      shift_to_apply = shift_to_apply,
      desired_origin = desired_origin,
      new_end = new_end,
      new_origin_shift_grid_units = new_origin_shift_grid_units,
       )
    return shift_info

  def shift_origin_to_match_original(self):
    '''
     Shift origin by self.origin_shift_grid_units to place origin in its
     original location
    '''
    original_origin = add_tuples_int(self.map_data().origin(),
                               self.origin_shift_grid_units)

    self.shift_origin(desired_origin = original_origin)

  def set_ncs_object(self, ncs_object):
    '''
      set the ncs object for this map_manager.  Incoming ncs_object must
     be compatible (shift_cart values must match).  Incoming ncs_object is
     deep_copied.
    '''
    assert isinstance(ncs_object, mmtbx.ncs.ncs.ncs)
    assert self.is_similar_ncs_object(ncs_object)
    self._ncs_object = deepcopy(ncs_object)

  def set_program_name(self, program_name = None):
    '''
      Set name of program doing work on this map_manager for output
      (string)
    '''
    self.program_name = program_name
    self._print("Program name of %s added" %(program_name))

  def add_limitation(self, limitation = None):
    '''
      Add a limitation from STANDARD_LIMITATIONS_DICT
      Supply the key (such as "map_is_sharpened")
    '''
    from iotbx.mrcfile import STANDARD_LIMITATIONS_DICT
    assert limitation in list(STANDARD_LIMITATIONS_DICT.keys())

    if not self.limitations:
      self.limitations = []
    self.limitations.append(limitation)
    self._print("Limitation of %s ('%s') added to map_manager" %(
      limitation, STANDARD_LIMITATIONS_DICT[limitation]))

  def add_label(self, label = None, verbose = False):
    '''
     Add a label (up to 80-character string) to write to output map.
     Default is to specify the program name and date
    '''
    if not self.labels:
      self.labels = []
    if len(label)>80:  label = label[:80]
    self.labels.reverse()  # put at beginning
    self.labels.append(to_str(label, codec = 'utf8')) # make sure it is a string
    self.labels.reverse()
    if verbose:
      self._print("Label added: %s " %(label))

  def write_map(self, file_name):

    '''
      Simple version of write

      file_name is output file name
      map_data is map_data object with 3D values for map. If not supplied,
        use self.map_data()

      Normally call with file_name (file to be written)
      Output labels are generated from existing self.labels,
      self.program_name, and self.limitations

    '''

    # Make sure we have map_data
    assert self.map_data()

    map_data = self.map_data()

    from iotbx.mrcfile import create_output_labels
    labels = create_output_labels(
      program_name = self.program_name,
      input_file_name = self.input_file_name,
      input_labels = self.labels,
      limitations = self.limitations)

    crystal_symmetry = self.unit_cell_crystal_symmetry()
    unit_cell_grid = self.unit_cell_grid
    origin_shift_grid_units = self.origin_shift_grid_units

    if map_data.origin()  ==  (0, 0, 0):  # Usual
      self._print("Writing map with origin at %s and size of %s to %s" %(
        str(origin_shift_grid_units), str(map_data.all()), file_name))
      from six.moves import StringIO
      f=StringIO()
      write_ccp4_map(
        file_name   = file_name,
        crystal_symmetry = crystal_symmetry, # unit cell and space group
        map_data    = map_data,
        unit_cell_grid = unit_cell_grid,  # optional gridding of full unit cell
        origin_shift_grid_units = origin_shift_grid_units, # optional origin shift
        labels      = labels,
        out = f)
      self._print(f.getvalue())
    else: # map_data has not been shifted to (0, 0, 0).  Shift it and then write
          # and then shift back
      self._print("Writing map after shifting origin")
      if self.origin_shift_grid_units and origin_shift_grid_units!= (0, 0, 0):
        self._print (
          "WARNING: map_data has origin at %s " %(str(map_data.origin()))+
         " and this map_manager will apply additional origin shift of %s " %(
          str(self.origin_shift_grid_units)))

      # Save where we are
      current_origin = map_data.origin()

      # Set origin at (0, 0, 0)
      self.shift_origin(desired_origin = (0, 0, 0))
      self.write_map(file_name = file_name)
      self.shift_origin(desired_origin = current_origin)

  def create_mask_around_density(self,
      resolution,
      molecular_mass = None,
      sequence = None,
      solvent_content = None):
    '''
      Use cctbx.maptbx.mask.create_mask_around_density to create a
       mask automatically

      Parameters are:
       resolution : required resolution of map
       molecular_mass: optional mass (Da) of object in density
       sequence: optional sequence of object in density
       solvent_content : optional solvent_content of map


    '''

    assert resolution is not None

    from cctbx.maptbx.mask import create_mask_around_density as cm
    self._created_mask = cm(map_manager = self,
        resolution = resolution,
        molecular_mass = molecular_mass,
        sequence = sequence,
        solvent_content = solvent_content, )

  def create_mask_around_edges(self,
      soft_mask_radius = None):
    '''
      Use cctbx.maptbx.mask.create_mask_around_edges to create a mask around
      edges of model
    '''

    assert soft_mask_radius is not None

    from cctbx.maptbx.mask import create_mask_around_edges as cm
    self._created_mask = cm(map_manager = self,
      soft_mask_radius = soft_mask_radius)

  def create_mask_around_atoms(self, model, mask_atoms_atom_radius):
    '''
      Use cctbx.maptbx.mask.create_mask_around_atoms to create a mask around
      atoms in model
    '''

    assert model is not None
    assert mask_atoms_atom_radius is not None

    from cctbx.maptbx.mask import create_mask_around_atoms as cm
    self._created_mask = cm(map_manager = self,
      model = model,
      mask_atoms_atom_radius = mask_atoms_atom_radius)

  def soft_mask(self, soft_mask_radius = None):
    '''
      Make mask a soft mask. Just uses method in create_mask_around_atoms
    '''
    assert self._created_mask is not None
    self._created_mask.soft_mask(soft_mask_radius = soft_mask_radius)

  def apply_mask(self, set_outside_to_mean_inside = False):
    '''
      Replace map_data with masked version based on current mask
      Just uses method in create_mask_around_atoms
    '''

    assert self._created_mask is not None
    new_mm = self._created_mask.apply_mask_to_other_map_manager(
      other_map_manager = self,
      set_outside_to_mean_inside = set_outside_to_mean_inside)
    self.set_map_data(map_data = new_mm.map_data())  # replace map data

  def delete_mask(self):
    self._created_mask = None

  def get_mask_as_map_manager(self):
    assert self._created_mask is not None
    return self._created_mask.map_manager()

  def set_map_data(self, map_data = None):
    '''
      Replace self.data with map_data. The two maps must have same gridding

      NOTE: This uses selections to copy all the data in map_data into
      self.data.  The map_data object is not associated with self.data, the
      data is simply copied.  Also as self.data is modified in place, any
      objects that currently are just pointers to self.data are affected.
    '''
    assert self.map_data().origin() == map_data.origin()
    assert self.map_data().all() == map_data.all()
    sel = flex.bool(map_data.size(), True)
    self.data.as_1d().set_selected(sel, map_data.as_1d())

  def as_full_size_map(self):
    '''
      Create a full-size map that with the current map inside it, padded by zero

      A little tricky because the starting map is going to have its origin at
      (0, 0, 0) but the map we are creating will have that point at
      self.origin_shift_grid_units.

      First use box.with_bounds to create map from -self.origin_shift_grid_units
       to -self.origin_shift_grid_units+self.unit_cell_grid-(1, 1, 1).  Then
      shift that map to place origin at (0, 0, 0)

      If the map is full size already, return the map as is
      If the map is bigger than full size stop as this is not suitable

    '''

    # Check to see if this is full size or bigger
    full_size_minus_working=subtract_tuples_int(self.unit_cell_grid,
      self.map_data().all())

    # Must not be bigger than full size already
    assert flex.double(full_size_minus_working).min_max_mean().min >= 0

    if full_size_minus_working == (0, 0, 0): # Exactly full size already. Done
      assert self.origin_shift_grid_units == (0, 0, 0)
      assert self.map_data().origin() == (0, 0, 0)
      return self


    working_lower_bounds = self.origin_shift_grid_units
    working_upper_bounds = tuple([i+j-1 for i, j in zip(working_lower_bounds,
      self.map_data().all())])
    lower_bounds = tuple([-i for i in self.origin_shift_grid_units])
    upper_bounds = tuple([i+j-1 for i, j in zip(lower_bounds, self.unit_cell_grid)])
    new_lower_bounds = tuple([i+j for i, j in zip(
      lower_bounds, self.origin_shift_grid_units)])
    new_upper_bounds = tuple([i+j for i, j in zip(
      upper_bounds, self.origin_shift_grid_units)])
    print("Creating full-size map padding outside of current map with zero",
      file = self.log)
    print("Bounds of current map: %s to %s" %(
     str(working_lower_bounds), str(working_upper_bounds)), file = self.log)
    print("Bounds of new map: %s to %s" %(
     str(new_lower_bounds), str(new_upper_bounds)), file = self.log)

    from cctbx.maptbx.box import with_bounds
    box = with_bounds(self,
       lower_bounds = lower_bounds,
       upper_bounds = upper_bounds,
       wrapping = False,
       log = self.log)
    box.map_manager().set_original_origin_and_gridding(original_origin = (0, 0, 0))

    box.map_manager().add_label(
       "Restored full size from box %s - %s, pad with zero" %(
     str(working_lower_bounds), str(working_upper_bounds)))
    assert box.map_manager().origin_shift_grid_units == (0, 0, 0)
    assert box.map_manager().map_data().origin() == (0, 0, 0)
    assert box.map_manager().map_data().all() == box.map_manager().unit_cell_grid
    assert box.map_manager().unit_cell_crystal_symmetry().is_similar_symmetry(
      box.map_manager().crystal_symmetry())
    return box.map_manager()

  def deep_copy(self):
    '''
      Return a deep copy of this map_manager object
      Uses customized_copy to deepcopy everything including map_data

      Origin does not have to be at (0, 0, 0) to apply
    '''
    return self.customized_copy(map_data = self.map_data())

  def customized_copy(self, map_data = None, origin_shift_grid_units = None,
      use_deep_copy_for_map_data = True):
    '''
      Return a customized deep_copy of this map_manager, replacing map_data with
      supplied map_data.

      The map_data and any _created_mask will be deep_copied before using
      them unless use_deep_copy_for_map_data = False

      Normally this customized_copy is applied with a map_manager
      that has already shifted the origin to (0, 0, 0) with shift_origin.

      Normally the new map_data will have the same dimensions of the current
      map_data. Normally new map_data will also have origin at (0, 0, 0).

      NOTE: It is permissible for map_data to have different bounds or origin
      than the current self.map_data.  In this case you must specify a new
      value of origin_shift_grid_units corresponding to this new map_data.
      This new origin_shift_grid_units specifies the original position in the
      full unit cell grid of the most-negative corner grid point of the
      new map_data. The new map_manager will still have the same unit
      cell dimensions and grid as the original.

      NOTE: It is permissible to get a customized copy before shifting the
      origin.  Applying with non-zero origin requires that:
         self.origin_shift_grid_units == (0, 0, 0)
         origin_shift_grid_units = (0, 0, 0)
         map_data.all() (size in each direction)  of current and new maps
            are the same.
         origins of current and new maps are the same
    '''

    # Make a deep_copy of map_data and _created_mask unless
    #    use_deep_copy_for_map_data = False

    if use_deep_copy_for_map_data:
      map_data = map_data.deep_copy()
      created_mask = deepcopy(self._created_mask)
    else:
      created_mask = self._created_mask

    assert map_data is not None # Require map data for the copy

    if map_data.origin() !=  (0, 0, 0):

      # Make sure all the assumptions are satisfied so we can just copy
      assert self.origin_shift_grid_units == (0, 0, 0)
      assert origin_shift_grid_units in [None, (0, 0, 0)]
      assert self.map_data().all() == map_data.all()
      assert self.map_data().origin() == map_data.origin()

      # Now just go ahead and copy using origin_shift_grid_units = (0, 0, 0)
      origin_shift_grid_units = (0, 0, 0)

    elif origin_shift_grid_units is None:  # use existing origin shift
      assert map_data.all()  ==  self.map_data().all() # bounds must be same
      origin_shift_grid_units = deepcopy(self.origin_shift_grid_units)

    # Deepcopy this object and then set map_data and origin_shift_grid_units

    mm = deepcopy(self)

    # Set things that are not necessarily the same as in self:
    mm.log=self.log
    mm.origin_shift_grid_units = origin_shift_grid_units  # specified above
    mm.data = map_data  # using self.data or a deepcopy (specified above)
    mm._created_mask = created_mask  # using self._created_mask or a
                                     #deepcopy (specified above)
    if self._ncs_object:
      mm._ncs_object = self._ncs_object.deep_copy()
    else:
      mm._ncs_object = None

    # Set up _crystal_symmetry for the new object
    mm.set_crystal_symmetry_of_partial_map() # Required and must be last

    return mm

  def is_full_size(self):
    '''
      Report if map is full unit cell
    '''
    if self.map_data().all()  ==  self.unit_cell_grid:
      return True
    else:
      return False

  def is_similar(self, other = None):
    # Check to make sure origin, gridding and symmetry are similar
    self._warning_message=""

    if tuple(self.origin_shift_grid_units) !=  tuple(
        other.origin_shift_grid_units):
      self._warning_message="Origin shift grid units "+  \
        "(%s) does not match other (%s)" %(
        str(self.origin_shift_grid_units),str(other.origin_shift_grid_units))
      return False
    if not self.unit_cell_crystal_symmetry().is_similar_symmetry(
      other.unit_cell_crystal_symmetry()):
      self._warning_message="Unit cell crystal symmetry"+ \
        "(%s) does not match other (%s)" %(
        str(self.unit_cell_crystal_symmetry()),
         str(other.unit_cell_crystal_symmetry()))
      return False
    if not self.crystal_symmetry().is_similar_symmetry(
      other.crystal_symmetry()):
      self._warning_message="Crystal symmetry"+ \
        "(%s) does not match other (%s)" %(
        str(self.crystal_symmetry()),
         str(other.crystal_symmetry()))
      return False
    if self.map_data().all()!=  other.map_data().all():
      self._warning_message="Existing map gridding "+ \
        "(%s) does not match other (%s)" %(
         str(self.map_data().all()),str(other.map_data().all()))
      return False
    if self.unit_cell_grid !=  other.unit_cell_grid:
      self._warning_message="Full map gridding "+ \
        "(%s) does not match other (%s)" %(
         str(self.map_data().all()),str(other.map_data().all()))
      return False

    # Make sure ncs objects are similar if both have one
    if self.ncs_object() is not None:
      if not other.ncs_object().is_similar_ncs_object(self.ncs_object()):
        text1=self.ncs_object().as_ncs_spec_string()
        text2=other.ncs_object().as_ncs_spec_string()
        self._warning_message="NCS object:\n%s\n does not match other:\n%s" %(
          text1,text2)
        return False
    return True

  def grid_units_to_cart(self, grid_units):
    ''' Convert grid units to cartesian coordinates '''
    x = grid_units[0]/self.unit_cell_grid[0]
    y = grid_units[1]/self.unit_cell_grid[1]
    z = grid_units[2]/self.unit_cell_grid[2]
    return self.unit_cell().orthogonalize(tuple((x, y, z)))

  def ncs_object(self):
    return self._ncs_object

  def shift_cart(self):
    '''
     Return the shift_cart of this map from its original location.

     (the negative of the origin shift ) in cartesian coordinates
     '''
    return tuple(
       [-x for x in self.grid_units_to_cart(self.origin_shift_grid_units)])

  def set_ncs_object_shift_cart_to_match_map(self, ncs_object):
    '''
      Set the ncs_object shift_cart to match map

      Overwrites any information in ncs_object on shift_cart
      Modifies ncs_object in place
    '''

    # Set shift_cart (shift since readin) to match shift_cart for
    #   map (shift of origin is opposite of shift applied)
    ncs_object.set_shift_cart(self.shift_cart())

  def set_model_symmetries_and_shift_cart_to_match_map(self,model):
    '''
      Set the model original and working crystal_symmetry to match map.

      Overwrites any information in model on symmetry and shift_cart
      Modifies model in place
    '''

    # Check if we really need to do anything
    if self.is_similar_model(model):
      return # already fine

    # Set original crystal symmetry to match map unit_cell_crystal_symmetry
    model.set_unit_cell_crystal_symmetry(self.unit_cell_crystal_symmetry())

    # Set crystal_symmetry to match map
    model.set_crystal_symmetry(self.crystal_symmetry())

    # Set shift_cart (shift since readin) to match shift_cart for
    #   map (shift of origin is opposite of shift applied)
    model.set_shift_cart(self.shift_cart())

  def is_similar_ncs_object(self, ncs_object, tol = 0.001):
    '''
      ncs_object is similar to this map_manager if shift_cart is
      the same as map
    '''

    ok=True
    text=""

    map_shift=flex.double(self.shift_cart())
    ncs_object_shift=flex.double(ncs_object.shift_cart())
    delta=map_shift-ncs_object_shift
    mmm=delta.min_max_mean()
    if mmm.min < -tol or mmm.max > tol: # shifts do not match
      text="Shift of ncs object (%s) does not match shift of map (%s)" %(
         str(ncs_object_shift),str(map_shift))
      ok=False

    self._warning_message=text
    return ok

  def is_similar_model(self, model, tol=0.001):
    '''
      Returns true if model has the same original and current symmetry and
      the same shift_cart as the map
    '''

    return self.is_compatible_model(model, require_similar=True, tol=tol)

  def is_compatible_model(self, model, require_similar=True, tol=0.001):
    '''
      Model is compatible with this map_manager if it is not specified as being
      different.

      They are different if:
        1. original and current symmetries are present and do not match
        2. model current symmetry does not match map original or current
        3. model has a shift_cart (shift applied) different than map shift_cart

      NOTE: a True result does not mean that the model crystal_symmetry matches
      the map crystal_symmetry.  It does mean that it is reasonable to set the
      model crystal_symmetry to match the map ones.

      If require_similar is True, then they are different if anything
      is different
    '''

    ok=None
    text=""

    model_uc=None
    model_uc=model.unit_cell_crystal_symmetry()
    model_sym=model.crystal_symmetry()
    map_uc=self.unit_cell_crystal_symmetry()
    map_sym=self.crystal_symmetry()

    text_model_uc="not defined"
    if model_uc:
      text_model_uc=str(model_uc).replace("\n"," ")
    text_model=str(model_sym).replace("\n"," ")
    text_map_uc=str(map_uc).replace("\n"," ")
    text_map=str(map_sym).replace("\n"," ")

    if require_similar and (not model_uc) and (
       not map_sym.is_similar_symmetry(map_uc)):
      ok=False
      text="Model and map are different because require_similar is set and "+\
          "model does not have original_crystal_symmetry, and " +\
        "model symmetry (%s) does not match map original symmetry " %(
          model_sym) +\
        "(%s). Current map symmetry is (%s) " %(
         text_map_uc,text_map)

    elif  model_uc and (not map_uc.is_similar_symmetry(map_sym) and (
         (not model_uc.is_similar_symmetry(map_uc)) or
         (not model_sym.is_similar_symmetry(map_sym) ) )):
       ok=False# model and map_manager symmetries present and do not match
       text="Model original (%s) and current (%s) crystal_symmetries " %(
          text_model_uc,text_model)+\
          "do not "+\
          "match map unit_cell (%s) and current (%s) symmetry" %(
           text_map_uc,text_map)
    elif (not model_sym.is_similar_symmetry(map_uc)) and (not
              model_sym.is_similar_symmetry(map_sym)):
       ok=False# model does not match either map symmetry
       text="Model current (%s) crystal_symmetry" %(
          text_model)+\
          "does not "+\
          "match map unit_cell (%s) or current (%s) symmetry" %(
           text_map_uc,text_map)

    else:  # match

       ok=True
       text="Model original (%s) and current (%s) crystal_symmetries " %(
          text_model_uc,text_model)+\
          "are compatible with "+\
          "map unit_cell (%s) and current (%s) symmetry" %(
           text_map_uc,text_map)

    assert isinstance(ok, bool)  # must have chosen

    map_shift_cart=self.shift_cart()
    if ok and (map_shift_cart != (0,0,0)):
      if model.shift_cart() is None: # map is shifted but not model
        ok=False
        text+=" However map is shifted (shift_cart=%s) but model is not" %(
           str(map_shift_cart))
      else:
        map_shift=flex.double(map_shift_cart)
        model_shift=flex.double(model.shift_cart())
        delta=map_shift-model_shift
        mmm=delta.min_max_mean()
        if mmm.min<-tol or mmm.max > tol: # shifts do not match
          ok=False
          text+=" However map shift "+\
              "(shift_cart=%s) does not match model shift (%s)" %(
           str(map_shift),str(model_shift))
    self._warning_message=text
    return ok

  def warning_message(self):
    if hasattr(self,'_warning_message'):
       return self._warning_message

  def ncs_cc(self):
    if hasattr(self,'_ncs_cc'):
       return self._ncs_cc

  def find_map_symmetry(self,
      include_helical_symmetry = False,
      symmetry_center = None,
      min_ncs_cc = None, 
      symmetry = None):
    '''
       Use run_get_symmetry_from_map tool in segment_and_split_map to find
       map symmetry and save it as an mmtbx.ncs.ncs.ncs object

       Here map symmetry is the reconstruction symmetry used to generate the
       map. Normally it is essentially perfect symmetry and normally the
       principal axes are aligned with x,y,z and normally the center is at
       the original center of the map.

       Sets self._warning_message if failure, sets self._ncs_object and
           self._ncs_cc if success

       This procedure may fail if the above assumptions do not hold.
       Optional center of map can be supplied, and minimum NCS correlation
       can also be supplied

       Requires that map_manager is already shifted to place origin at (0, 0, 0)

       Assumes that center of symmetry is at (1/2, 1/2, 1/2) in the full map

       It is optional to include search for helical symmetry. Reason is that
       this is much slower than other symmetries.

       symmetry (symbol such as c1, O, D7) can be supplied and search will be
       limited to that symmetry
    '''

    assert self.origin_is_zero()

    self._warning_message = ""
    self._ncs_cc = None

    from cctbx.maptbx.segment_and_split_map import \
       run_get_ncs_from_map, get_params

    if symmetry_center is None:
      # Most likely map center is (1/2,1/2,1/2) in full grid
      full_unit_cell=self.unit_cell_crystal_symmetry(
            ).unit_cell().parameters()[:3]
      symmetry_center=[]
      for x, sc in zip(full_unit_cell, self.shift_cart()):
        symmetry_center.append(0.5*x + sc)
      symmetry_center = tuple(symmetry_center)

    params = get_params(args=[],
      symmetry = symmetry,
      include_helical_symmetry = include_helical_symmetry,
      symmetry_center = symmetry_center,
      min_ncs_cc = min_ncs_cc,
      return_params_only = True,
      )


    new_ncs_obj, ncs_cc, ncs_score = run_get_ncs_from_map(params = params,
      map_data = self.map_data(),
      crystal_symmetry = self.crystal_symmetry(),
      out = sys.stdout, #self.log,
      )
    if new_ncs_obj:
      self._ncs_object = new_ncs_obj
      self._ncs_cc = ncs_cc
    else:
      self._warning_message = "No map symmetry found; ncs_cc cutoff of %s" %(
        min_ncs_cc)

  def map_as_fourier_coefficients(self, high_resolution = None):
    '''
       Convert a map to Fourier coefficients to a resolution of high_resolution,
       if high_resolution is provided, otherwise box full of map coefficients
       will be created.

       NOTE: Fourier coefficients are relative the working origin (not
       original origin).  A map calculated from the Fourier coefficients will
       superimpose on the working (current map) without origin shifts.

       This method and fourier_coefficients_as_map interconvert map_data and
       map_coefficients without changin origin.  Both are intended for use
       with map_data that has an origin at (0, 0, 0).
    '''
    assert self.map_data()
    assert self.map_data().origin() == (0, 0, 0)
    return miller.structure_factor_box_from_map(
      crystal_symmetry = self.crystal_symmetry(),
      include_000      = True,
      map              = self.map_data(),
      d_min            = high_resolution)

  def fourier_coefficients_as_map(self, map_coeffs):
    '''
       Convert Fourier coefficients into to a real-space map with gridding
       matching this existing map_manager.

       Requires that this map_manager has origin at (0, 0, 0) (i.e.,
       shift_origin() has been applied if necessary)

       NOTE: Assumes that the map_coeffs are in the same frame of reference
       as this map_manager (i.e., similar to those that would be written out
       using map_as_fourier_coefficients).
    '''

    assert isinstance(map_coeffs, miller.array)
    assert isinstance(map_coeffs.data(), flex.complex_double)
    assert self.map_data() and self.map_data().origin() == (0, 0, 0)

    return maptbx.map_coefficients_to_map(
      map_coeffs       = map_coeffs,
      crystal_symmetry = self.crystal_symmetry(),
      n_real           = self.map_data().all())

def subtract_tuples_int(t1, t2):
  return tuple(flex.int(t1)-flex.int(t2))

def add_tuples_int(t1, t2):
  return tuple(flex.int(t1)+flex.int(t2))
