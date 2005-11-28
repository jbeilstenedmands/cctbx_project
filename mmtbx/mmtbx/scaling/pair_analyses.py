from cctbx import maptbx
from cctbx import miller
from cctbx import crystal
from cctbx import sgtbx
from cctbx import adptbx
from libtbx import table_utils
import cctbx.sgtbx.lattice_symmetry
import cctbx.sgtbx.cosets
from cctbx.array_family import flex
from libtbx.utils import Sorry, date_and_time, multi_out
import iotbx.phil
from iotbx import reflection_file_reader
from iotbx import reflection_file_utils
from iotbx import crystal_symmetry_from_any
import mmtbx.scaling
from mmtbx.scaling import absolute_scaling
from mmtbx.scaling import matthews, twin_analyses
from mmtbx.scaling import basic_analyses, data_statistics
import libtbx.phil.command_line
from cStringIO import StringIO
from scitbx.python_utils import easy_pickle
import sys, os, math


class reindexing(object):
  __doc__=""" Reindexing matrices """
  def __init__(self,
               set_a,
               set_b,
               out=None,
               relative_length_tolerance=0.05,
               absolute_angle_tolerance=3.0,
               lattice_symmetry_max_delta=3.0):

    self.set_a = set_a
    self.set_b = set_b

    ##----------
    self.change_of_basis_op_to_minimum_cell_a=\
      set_a.change_of_basis_op_to_minimum_cell()
    self.change_of_basis_op_to_minimum_cell_b=\
      set_b.change_of_basis_op_to_minimum_cell()
    ##----------
    self.minimum_cell_symmetry_a = crystal.symmetry.change_basis(
      set_a,
      cb_op=self.change_of_basis_op_to_minimum_cell_a)
    self.minimum_cell_symmetry_b = crystal.symmetry.change_basis(
      set_b,
      cb_op=self.change_of_basis_op_to_minimum_cell_b)
    ##----------
    self.lattice_group_a = sgtbx.lattice_symmetry.group(
      self.minimum_cell_symmetry_a.unit_cell(),
      max_delta=lattice_symmetry_max_delta)
    self.lattice_group_a.expand_inv(sgtbx.tr_vec((0,0,0)))
    self.lattice_group_a.make_tidy()

    self.lattice_group_b = sgtbx.lattice_symmetry.group(
      self.minimum_cell_symmetry_b.unit_cell(),
      max_delta=lattice_symmetry_max_delta)
    self.lattice_group_b.expand_inv(sgtbx.tr_vec((0,0,0)))
    self.lattice_group_b.make_tidy()
    ##----------
    self.lattice_symmetry_a = crystal.symmetry(
      unit_cell=self.minimum_cell_symmetry_a.unit_cell(),
      space_group_info=sgtbx.space_group_info(group=self.lattice_group_a),
      assert_is_compatible_unit_cell=False)

    self.lattice_symmetry_b = crystal.symmetry(
      unit_cell=self.minimum_cell_symmetry_b.unit_cell(),
      space_group_info=sgtbx.space_group_info(group=self.lattice_group_b),
      assert_is_compatible_unit_cell=False)
    ##----------
    self.intensity_symmetry_a = \
       self.minimum_cell_symmetry_a.reflection_intensity_symmetry(
         anomalous_flag=set_a.anomalous_flag())

    self.intensity_symmetry_b = \
       self.minimum_cell_symmetry_b.reflection_intensity_symmetry(
         anomalous_flag=set_b.anomalous_flag())
    ##----------
    c_inv_rs = self.minimum_cell_symmetry_a.unit_cell().\
      similarity_transformations(
        other=self.minimum_cell_symmetry_b.unit_cell(),
        relative_length_tolerance=relative_length_tolerance,
        absolute_angle_tolerance=absolute_angle_tolerance)


    min_bases_msd = None
    similarity_cb_op = None

    for c_inv_r in c_inv_rs:
      c_inv = sgtbx.rt_mx(sgtbx.rot_mx(c_inv_r))
      cb_op = sgtbx.change_of_basis_op(c_inv).inverse()
      bases_msd = self.minimum_cell_symmetry_a.unit_cell() \
        .bases_mean_square_difference(
          other=cb_op.apply(self.minimum_cell_symmetry_b.unit_cell()))
      if (min_bases_msd is None
          or min_bases_msd > bases_msd):
        min_bases_msd = bases_msd
        similarity_cb_op = cb_op
    if (similarity_cb_op is None): return []

    common_lattice_group = sgtbx.space_group(self.lattice_group_a)
    for s in self.lattice_group_b.build_derived_acentric_group() \
               .change_basis(similarity_cb_op):
      try: common_lattice_group.expand_smx(s)
      except RuntimeError: return []
    common_lattice_group.make_tidy()
    result = []
    for s in sgtbx.cosets.double_unique(
               g=common_lattice_group,
               h1=self.intensity_symmetry_a.space_group()
                   .build_derived_acentric_group()
                   .make_tidy(),
               h2=self.intensity_symmetry_b.space_group()
                   .build_derived_acentric_group()
                   .change_basis(similarity_cb_op)
                   .make_tidy()):
      if (s.r().determinant() > 0):
        result.append(sgtbx.change_of_basis_op(s) * similarity_cb_op)
    self.matrices = result
    self.cc_values= []
    self.matches = []
    self.table=None
    self.analyse()

  def combined_cb_op(self, cb_op):
    s = self.change_of_basis_op_to_minimum_cell_a
    o = self.change_of_basis_op_to_minimum_cell_b
    return s.inverse() * cb_op.new_denominators(s) * o

  def analyse(self):
    ## As the coset decompision is carried out on the minimum cell
    ## The re-indexing laws need to be transform to the original
    ## spacegroup
    table_data=[]
    for cb_op in self.matrices:
      cb_op_comb = self.combined_cb_op(cb_op)
      ## FIX ASU MAPPING HERE

      tmp_set_b = self.set_b.change_basis(cb_op_comb).map_to_asu()
      tmp_set_a, tmp_set_b = self.set_a.map_to_asu().common_sets(
        tmp_set_b,
        assert_is_similar_symmetry=False)
      tmp_cc = tmp_set_a.correlation(
        tmp_set_b,
        assert_is_similar_symmetry=False)
      ## STore the cc values
      self.cc_values.append(  tmp_cc.coefficient()  )
      self.matches.append(
        float(tmp_set_a.indices().size())/float(self.set_a.indices().size()))




  def select_and_transform(self,
                           out=None,
                           matches_cut_off=0.75,
                           input_array=None):
    if out is None:
      out = sys.stdout
    ## hopsa
    max_cc=-1.0
    location = 0
    table_data=[]
    for ii in range(len(self.matrices)):
      table_data.append(
        [self.matrices[ii].as_hkl(),
         "%4.3f"%(self.cc_values[ii]),
         "%4.3f"%(self.matches[ii]),
         '   ']
        )

      if self.matches[ii]>=matches_cut_off:
        if max_cc<self.cc_values[ii]:
          max_cc = self.cc_values[ii]
          location = ii

    legend = ('Operator', 'Correlation', 'matches (%)', 'choice')
    table_data[location][3]=' <--- '
    self.table = table_utils.format([legend]+table_data,
                                       comments=None,
                                       has_header=True,
                                       separate_rows=False,
                                       prefix='| ',
                                       postfix=' |')

    print >> out, self.table

    if input_array is not None:
      return input_array.change_basis( self.matrices[location] ).map_to_asu()\
             .set_observation_type( input_array )


class delta_generator(object):
  def __init__(self,nat,der):
    self.nat=nat.deep_copy()
    self.der=der.deep_copy()
    assert self.nat.is_real_array()
    assert self.nat.is_real_array()

    if self.nat.is_xray_intensity_array():
      self.nat.f_sq_as_f()
    if self.der.is_xray_intensity_array():
      self.der.f_sq_as_f()

    self.nat,self.der = self.nat.common_sets(self.der)

    self.delta_f=self.nat.customized_copy(
      data = ( self.der.data() - self.nat.data() ),
      sigmas = flex.sqrt( self.der.sigmas()*self.der.sigmas()+
                          self.nat.sigmas()*self.nat.sigmas() )
      ).set_observation_type( self.nat )

    self.abs_delta_f=self.nat.customized_copy(
      data = flex.abs( self.der.data() - self.nat.data() ),
      sigmas = flex.sqrt( self.der.sigmas()*self.der.sigmas()+
                          self.nat.sigmas()*self.nat.sigmas() )
      ).set_observation_type( self.der )

    if not self.nat.is_xray_intensity_array():
      self.nat.f_as_f_sq()
    if not self.der.is_xray_intensity_array():
      self.der.f_as_f_sq()

    self.delta_i=self.nat.customized_copy(
      data = ( self.der.data() - self.nat.data() ),
      sigmas = flex.sqrt( self.der.sigmas()*self.der.sigmas()+
                          self.nat.sigmas()*self.nat.sigmas() )
      ).set_observation_type( self.nat )

    self.abs_delta_i=self.nat.customized_copy(
      data = flex.abs( self.der.data() - self.nat.data() ),
      sigmas = flex.sqrt( self.der.sigmas()*self.der.sigmas()+
                          self.nat.sigmas()*self.nat.sigmas() )
      ).set_observation_type( self.der )



class outlier_rejection(object):
  def __init__(self,
               nat,
               der,
               cut_level_rms=3,
               cut_level_sigma=0,
               method={'solve':False,'rms':False, 'rms_and_sigma':True},
               out=None
               ):
    self.out=out
    self.method = method
    if self.out == None:
      self.out = sys.stdout

    self.cut_level_rms=cut_level_rms
    self.cut_level_sigma=cut_level_sigma
    ## Just make sure that we have the common sets
    self.nat = nat.deep_copy()
    self.der = der.deep_copy()
    self.nat, self.der = self.nat.common_sets(self.der)
    #Make sure we have amplitudes
    assert self.nat.is_real_array()
    assert self.nat.is_real_array()

    if self.nat.is_xray_intensity_array():
      self.nat=self.nat.f_sq_as_f()
    if self.der.is_xray_intensity_array():
      self.der=self.der.f_sq_as_f()

    ## Construct delta f's
    delta_gen = delta_generator( self.nat, self.der )
    self.delta_f = delta_gen.abs_delta_f
    ## Set up a binner please
    self.delta_f.setup_binner_d_star_sq_step(auto_binning=True)
    ## for each bin, I would like to compute
    ## mean dF**2
    ## mean sigma**2
    self.mean_df2 = self.delta_f.mean_of_intensity_divided_by_epsilon(
      use_binning=True,
      return_fail=1e12)
    self.mean_sdf2 = self.delta_f.mean_of_squared_sigma_divided_by_epsilon(
      use_binning=True,
      return_fail=1e12)

    self.result = flex.bool(  self.delta_f.indices().size(), True )

    self.detect_outliers()
    self.remove_outliers()

  def detect_outliers(self):
    count_true = 0
    if (self.method['solve']):
      count_true+=1
    if (self.method['rms']):
      count_true+=1
    if (self.method['rms_and_sigma']):
      count_true+=1


    if not count_true==1:
      raise Sorry("Outlier removal protocol not specified properly")

    if (self.method['solve']):
      self.detect_outliers_solve()
    if (self.method['rms']):
      self.detect_outliers_rms()
    if (self.method['rms_and_sigma']):
      self.detect_outliers_sigma()




  def detect_outliers_solve(self):
    """
    TT says:
    I toss everything > 3 sigma in the scaling,
    where sigma comes from the rms of everything being scaled:

    sigma**2 = <delta**2>- <experimental-sigmas**2>

    Then if a particular
    delta**2 > 3 sigma**2 + experimental-sigmas**2
    then I toss it.
    """
    terwilliger_sigma_array = flex.double(self.mean_df2.data) -\
                              flex.double(self.mean_sdf2.data)

    for bin_number in self.delta_f.binner().range_all():
      ## The selection tells us wether or not somthing is in the correct bin
      selection =  self.delta_f.binner().selection( bin_number ).iselection()
      ## Now just make a global check to test for outlierness:
      tmp_sigma_array =  terwilliger_sigma_array[bin_number] -\
                         self.delta_f.sigmas()*self.delta_f.sigmas()
      tmp_sigma_array = flex.sqrt(tmp_sigma_array)*self.cut_level_rms

      potential_outliers = ( self.delta_f.data()  >  tmp_sigma_array )
      potential_outliers =  potential_outliers.select( selection )

      self.result = self.result.set_selected( selection, potential_outliers )

    print >> self.out
    print >> self.out, " %8i potential outliers detected" %(
      self.result.count(True) )
    print >> self.out, " They will be removed from the data set"
    print >> self.out


  def detect_outliers_rms(self):
    for bin_number in self.delta_f.binner().range_all():
      selection =  self.delta_f.binner().selection( bin_number ).iselection()
      potential_outliers = (
        self.delta_f.data()  >  self.cut_level_rms*math.sqrt(
        self.mean_df2.data[bin_number])  )
      potential_outliers =  potential_outliers.select( selection )
      self.result = self.result.set_selected( selection, potential_outliers )

    print >> self.out
    print >> self.out, " %8i potential outliers detected" %(
      self.result.count(True) )
    print >> self.out, " They will be removed from the data set"
    print >> self.out


  def detect_outliers_sigma(self):
    ## Locate outliers in native
    potential_outlier_nat = (self.nat.data()/self.nat.sigmas()
                               < self.cut_level_sigma)
    nat_select = potential_outlier_nat.iselection()

    ## Locate outliers in derivative
    potential_outlier_der = (self.der.data()/self.der.sigmas()
                               <self.cut_level_sigma)
    der_select = potential_outlier_der.iselection()

    for bin_number in self.delta_f.binner().range_all():
      ## RMS outlier removal
      selection =  self.delta_f.binner().selection( bin_number ).iselection()
      potential_outliers = (
        self.delta_f.data()  >  self.cut_level_rms*math.sqrt(
        self.mean_df2.data[bin_number])  )
      potential_outliers =  potential_outliers.select( selection )
      self.result = self.result.set_selected( selection, potential_outliers )

    self.result = self.result.set_selected( nat_select, True )
    self.result = self.result.set_selected( der_select, True )

    print >> self.out
    print >> self.out, " %8i potential outliers detected" %(
      self.result.count(True) )
    print >> self.out, " They will be removed from the data set"
    print >> self.out


  def remove_outliers(self):
    potential_outliers = self.nat.select( self.result )

    matches = miller.match_indices( self.nat.indices(),
                                    potential_outliers.indices()  )

    self.nat = self.nat.select( matches.single_selection(0) )

    self.nat, self.der = self.nat.common_sets(self.der)
