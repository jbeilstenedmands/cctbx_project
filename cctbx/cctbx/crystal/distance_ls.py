from cctbx.crystal import minimization
from cctbx.crystal import pair_asu_table
from cctbx import restraints
from cctbx import xray
from cctbx import crystal
from cctbx import sgtbx
from cctbx.array_family import flex
from scitbx import matrix as mx
from scitbx.python_utils.misc import adopt_init_args
import scitbx.lbfgs
from libtbx.itertbx import count

if (1):
  flex.set_random_seed(0)

class restraint_parameters:

  def __init__(self, distance_ideal, weight):
    adopt_init_args(self, locals())

restraint_parameters_si_o = restraint_parameters(1.61, 2.0)
restraint_parameters_o_si_o = restraint_parameters(2.629099, 0.41)
restraint_parameters_si_o_si = restraint_parameters(3.070969, 0.2308)

class add_oxygen:

  def __init__(self, si_structure, si_pair_asu_table):
    self.structure = si_structure.deep_copy_scatterers()
    self.bond_sym_proxies = []
    sites_frac = si_structure.sites_frac()
    si_asu_mappings = si_pair_asu_table.asu_mappings
    i_oxygen = count(1)
    for i_seq,table_i_seq in enumerate(si_pair_asu_table.table):
      rt_mx_i_inv = si_asu_mappings.get_rt_mx(i_seq, 0).inverse()
      site_frac_i = sites_frac[i_seq]
      for j_seq,j_sym_groups in table_i_seq.items():
        for i_group,j_sym_group in enumerate(j_sym_groups):
          if (j_seq < i_seq): continue
          j_sym = j_sym_group[0]
          rt_mx_ji = rt_mx_i_inv.multiply(
            si_asu_mappings.get_rt_mx(j_seq, j_sym))
          site_frac_ji = rt_mx_ji * sites_frac[j_seq]
          bond_center = (mx.col(site_frac_i) + mx.col(site_frac_ji)) / 2
          i_seq_o = self.structure.scatterers().size()
          self.structure.add_scatterer(xray.scatterer(
            label="O%d"%i_oxygen.next(),
            site=bond_center))
          self.bond_sym_proxies.append(pair_asu_table.pair_sym_proxy(
            i_seqs=[i_seq, i_seq_o],
            rt_mx=sgtbx.rt_mx(1,1)))
          self.bond_sym_proxies.append(pair_asu_table.pair_sym_proxy(
            i_seqs=[j_seq, i_seq_o],
            rt_mx=rt_mx_ji.inverse_cancel()))

def make_o_si_o_asu_table(si_o_structure, si_o_bond_asu_table):
  scatterers = si_o_structure.scatterers()
  asu_mappings = si_o_bond_asu_table.asu_mappings
  o_si_o_asu_table = pair_asu_table.pair_asu_table(
    asu_mappings=asu_mappings)
  for i_seq,table_i_seq in enumerate(si_o_bond_asu_table.table):
    if (scatterers[i_seq].scattering_type != "Si"): continue
    pair_list = []
    for j_seq,j_sym_groups in table_i_seq.items():
      if (scatterers[j_seq].scattering_type != "O"): continue
      for i_group,j_sym_group in enumerate(j_sym_groups):
        for j_sym in j_sym_group:
          pair_list.append((j_seq,j_sym))
    for i_jj1 in xrange(0,len(pair_list)-1):
      jj1 = pair_list[i_jj1]
      rt_mx_jj1_inv = asu_mappings.get_rt_mx(*jj1).inverse()
      for i_jj2 in xrange(i_jj1+1,len(pair_list)):
        jj2 = pair_list[i_jj2]
        rt_mx_jj21 = rt_mx_jj1_inv.multiply(asu_mappings.get_rt_mx(*jj2))
        o_si_o_asu_table.add_pair(
          i_seq=jj1[0],
          j_seq=jj2[0],
          rt_mx_ji=rt_mx_jj21)
  return o_si_o_asu_table

def get_all_proxies(
      structure,
      bond_asu_table,
      nonbonded_distance_cutoff,
      minimal=00000):
  bond_asu_proxies = restraints.shared_bond_asu_proxy()
  repulsion_asu_proxies = restraints.shared_repulsion_asu_proxy()
  pair_generator = crystal.neighbors_fast_pair_generator(
    asu_mappings=bond_asu_table.asu_mappings,
    distance_cutoff=nonbonded_distance_cutoff,
    minimal=minimal)
  for pair in pair_generator:
    if (pair in bond_asu_table):
      bond_asu_proxies.append(restraints.bond_asu_proxy(
        pair=pair, distance_ideal=0, weight=0))
    else:
      repulsion_asu_proxies.append(restraints.repulsion_asu_proxy(
        pair=pair, vdw_radius=-1))
  return bond_asu_proxies, repulsion_asu_proxies

def edit_bond_asu_proxies(structure, asu_mappings, bond_asu_proxies):
  scatterers = structure.scatterers()
  for proxy in bond_asu_proxies:
    i_seqs = proxy.pair.i_seq, proxy.pair.j_seq
    scattering_types = [scatterers[i].scattering_type for i in i_seqs]
    scattering_types.sort()
    if (scattering_types == ["Si", "Si"]):
      proxy.distance_ideal = restraint_parameters_si_o_si.distance_ideal
      proxy.weight = restraint_parameters_si_o_si.weight
    elif (scattering_types == ["O", "Si"]):
      proxy.distance_ideal = restraint_parameters_si_o.distance_ideal
      proxy.weight = restraint_parameters_si_o.weight
    elif (scattering_types == ["O", "O"]):
      proxy.distance_ideal = restraint_parameters_o_si_o.distance_ideal
      proxy.weight = restraint_parameters_o_si_o.weight
    else:
      raise AssertionError("Unknown scattering type pair.")

def edit_repulsion_asu_proxies(structure, asu_mappings, repulsion_asu_proxies):
  scatterers = structure.scatterers()
  for proxy in repulsion_asu_proxies:
    i_seqs = proxy.pair.i_seq, proxy.pair.j_seq
    scattering_types = [scatterers[i].scattering_type for i in i_seqs]
    scattering_types.sort()
    if (scattering_types == ["Si", "Si"]):
      proxy.vdw_radius = 3.1
    elif (scattering_types == ["O", "Si"]):
      proxy.vdw_radius = 1.5
    elif (scattering_types == ["O", "O"]):
      proxy.vdw_radius = 2.0
    else:
      raise AssertionError("Unknown scattering type pair.")

class show_pairs:

  def __init__(self, structure, pair_asu_table):
    self.distances = flex.double()
    self.pair_counts = flex.size_t()
    unit_cell = structure.unit_cell()
    scatterers = structure.scatterers()
    sites_frac = structure.sites_frac()
    asu_mappings = pair_asu_table.asu_mappings
    for i_seq,table_i_seq in enumerate(pair_asu_table.table):
      rt_mx_i_inv = asu_mappings.get_rt_mx(i_seq, 0).inverse()
      site_frac_i = sites_frac[i_seq]
      pair_count = 0
      for j_seq,j_sym_groups in table_i_seq.items():
        site_frac_j = sites_frac[j_seq]
        for i_group,j_sym_group in enumerate(j_sym_groups):
          for i_j_sym,j_sym in enumerate(j_sym_group):
            rt_mx_ji = rt_mx_i_inv.multiply(
              asu_mappings.get_rt_mx(j_seq, j_sym))
            distance = unit_cell.distance(site_frac_i, rt_mx_ji * site_frac_j)
            self.distances.append(distance)
            if (pair_count == 0):
              print "%s(%d):" % (scatterers[i_seq].label, i_seq+1)
            print "  %-10s" % ("%s(%d):" % (scatterers[j_seq].label, j_seq+1)),
            print "%8.4f" % distance,
            if (i_j_sym != 0): print "sym. equiv.",
            print
            pair_count += 1
      self.pair_counts.append(pair_count)

def show_nonbonded_interactions(structure, asu_mappings, nonbonded_proxies):
  distances = flex.double()
  unit_cell = structure.unit_cell()
  scatterers = structure.scatterers()
  sites_frac = structure.sites_frac()
  for proxy in nonbonded_proxies:
    pair = proxy.pair
    i_seq, j_seq, j_sym = pair.i_seq, pair.j_seq, pair.j_sym
    rt_mx_i_inv = asu_mappings.get_rt_mx(i_seq, 0).inverse()
    rt_mx_ji = rt_mx_i_inv.multiply(asu_mappings.get_rt_mx(j_seq, j_sym))
    pair_labels = "%s(%d) - %s(%d):" % (
      scatterers[i_seq].label, i_seq+1,
      scatterers[j_seq].label, j_seq+1)
    distance = unit_cell.distance(
      sites_frac[i_seq], rt_mx_ji*sites_frac[j_seq])
    distances.append(distance)
    print "%-20s %8.4f" % (pair_labels, distance)
  return distances

def distance_and_repulsion_least_squares(
      si_structure,
      distance_cutoff,
      nonbonded_distance_cutoff,
      connectivities=None):
  si_structure.show_summary().show_scatterers()
  print
  si_asu_mappings = si_structure.asu_mappings(
    buffer_thickness=distance_cutoff)
  si_pair_asu_table = pair_asu_table.pair_asu_table(
    asu_mappings=si_asu_mappings)
  si_pair_asu_table.add_all_pairs(distance_cutoff=distance_cutoff)
  si_pairs = show_pairs(
    structure=si_structure,
    pair_asu_table=si_pair_asu_table)
  if (connectivities is not None):
    assert list(si_pairs.pair_counts) == connectivities
  print
  si_o = add_oxygen(
    si_structure=si_structure,
    si_pair_asu_table=si_pair_asu_table)
  si_o.structure.show_summary().show_scatterers()
  print
  assert nonbonded_distance_cutoff \
       > flex.max(si_pairs.distances)/2.*(1-1.e-6)
  si_o_asu_mappings = si_o.structure.asu_mappings(
    buffer_thickness=nonbonded_distance_cutoff)
  si_o_bond_asu_table = pair_asu_table.pair_asu_table(
    asu_mappings=si_o_asu_mappings)
  si_o_bond_asu_table.add_pair_sym_proxies(proxies=si_o.bond_sym_proxies)
  si_o_bonds = show_pairs(
    structure=si_o.structure,
    pair_asu_table=si_o_bond_asu_table)
  n_si = si_pairs.pair_counts.size()
  n_si_o = si_o_bonds.pair_counts.size()
  assert si_o_bonds.pair_counts[:n_si].all_eq(si_pairs.pair_counts)
  assert si_o_bonds.pair_counts[n_si:].count(2) == n_si_o-n_si
  print
  o_si_o_asu_table = make_o_si_o_asu_table(
    si_o_structure=si_o.structure,
    si_o_bond_asu_table=si_o_bond_asu_table)
  o_si_o_pairs = show_pairs(
    structure=si_o.structure,
    pair_asu_table=o_si_o_asu_table)
  assert o_si_o_pairs.pair_counts[:n_si].all_eq(0)
  if (si_pairs.pair_counts.count(4) == n_si):
    assert o_si_o_pairs.pair_counts[n_si:].all_eq(6)
  print
  if (1):
    si_o_bond_asu_table.add_pair_sym_proxies(
      proxies=si_pair_asu_table.extract_pair_sym_proxies())
  if (1):
    si_o_bond_asu_table.add_pair_sym_proxies(
      proxies=o_si_o_asu_table.extract_pair_sym_proxies())
  bond_asu_proxies, repulsion_asu_proxies = get_all_proxies(
    structure=si_o.structure,
    bond_asu_table=si_o_bond_asu_table,
    nonbonded_distance_cutoff=nonbonded_distance_cutoff)
  nonbonded_distances = show_nonbonded_interactions(
    structure=si_o.structure,
    asu_mappings=si_o_asu_mappings,
    nonbonded_proxies=repulsion_asu_proxies)
  assert flex.min(nonbonded_distances) \
       > flex.min(si_o_bonds.distances)*(1-1.e-6)
  print
  edit_bond_asu_proxies(
    structure=si_o.structure,
    asu_mappings=si_o_asu_mappings,
    bond_asu_proxies=bond_asu_proxies)
  edit_repulsion_asu_proxies(
    structure=si_o.structure,
    asu_mappings=si_o_asu_mappings,
    repulsion_asu_proxies=repulsion_asu_proxies)
  if (0):
    repulsion_asu_proxies = None
  sites_cart = si_o.structure.sites_cart()
  print "Energies at start:"
  energies = minimization.energies(
    sites_cart=sites_cart,
    asu_mappings=si_o_asu_mappings,
    bond_asu_proxies=bond_asu_proxies,
    repulsion_asu_proxies=repulsion_asu_proxies,
    compute_gradients=0001)
  energies.show()
  print
  minimized = minimization.lbfgs(
    sites_cart=sites_cart,
    asu_mappings=si_o_asu_mappings,
    bond_asu_proxies=bond_asu_proxies,
    repulsion_asu_proxies=repulsion_asu_proxies,
    lbfgs_termination_params=scitbx.lbfgs.termination_parameters(
      max_iterations=1000))
  print "Energies at end:"
  minimized.target_result.show()
  print
  minimized_si_o_structure = si_o.structure.deep_copy_scatterers()
  minimized_si_o_structure.set_sites_cart(sites_cart)
  show_pairs(
    structure=minimized_si_o_structure,
    pair_asu_table=si_o_bond_asu_table)
  print
