from __future__ import division, print_function
import sys, time
import iotbx.phil
from libtbx import group_args
from libtbx.utils import Sorry
from mmtbx.ringer import iterate_over_residues
from mmtbx.ringer import em_rolling
from mmtbx.ringer import em_scoring

master_params_str = '''
sampling_angle = 5
  .type = int
  .input_size = 64
sampling_method = linear *spline direct
  .help = Method for sampling
  .type = choice(multi=False)
grid_spacing = 1./5
  .type = float
scaling = *sigma volume
  .help = Method for map scaling.
  .type = choice(multi=False)
rolling_window_threshold = 0
  .type = float(value_min=0)
  .help = Threshold for calculating statistics across rolling windows of residues
skip_alt_confs = True
  .type = bool
nproc = 1
  .type = int
  .short_caption = Number of processors
  .input_size = 64
  '''

def master_params():
  return iotbx.phil.parse(master_params_str, process_includes=False)

class emringer(object):
  def __init__(self, model, map_coeffs, ccp4_map, params, out, quiet):
    self.model      = model
    self.map_coeffs = map_coeffs
    self.ccp4_map   = ccp4_map
    self.params     = params
    self.out        = out
    self.quiet      = quiet

  def validate(self):
    assert not None in [self.model, self.params, self.out]
    if (self.model is None):
      raise Sorry("Model is required.")
    if (self.map_coeffs is None and self.ccp4_map is None):
      raise Sorry("Map or map coefficients are required.")

  def run(self):
    hierarchy = self.model.get_hierarchy()
    hierarchy.atoms().reset_i_seq()

    crystal_symmetry_model = self.model.crystal_symmetry()

    self.ringer_result = iterate_over_residues(
      pdb_hierarchy          = hierarchy,
      map_coeffs             = self.map_coeffs,
      ccp4_map               = self.ccp4_map,
      crystal_symmetry_model = crystal_symmetry_model,
      params                 = self.params,
      log                    = self.out
      ).results

    plots_dir = self.params.output_base + "_plots"

    import matplotlib
    matplotlib.use("Agg")
    self.scoring_result = em_scoring.main(
      file_name      = self.params.output_base,
      ringer_result  = self.ringer_result,
      out_dir        = plots_dir,
      sampling_angle = self.params.sampling_angle,
      quiet          = self.quiet,
      out            = self.out)

    rolling_window_threshold = self.params.rolling_window_threshold
    self.rolling_result = em_rolling.main(
      ringer_results = self.ringer_result,
      dir_name       = plots_dir,
      threshold      = rolling_window_threshold, #scoring.optimal_threshold,
      graph          = False,
      save           = not self.quiet,
      out            = self.out)

  def get_results(self):
    return group_args(
      ringer_result  = self.ringer_result,
      scoring_result = self.scoring_result,
      rolling_result = self.rolling_result)
