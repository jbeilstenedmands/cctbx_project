from cctbx import sgtbx

class subgroups:

  def __init__(self, parent_group_info):
    self._p_groups = []
    self.z2p_op = parent_group_info.group().z2p_op()
    p_parent_group_info = parent_group_info.change_basis(self.z2p_op)
    p_parent_group = p_parent_group_info.group()
    assert p_parent_group.order_p() == p_parent_group.order_z()
    p_parent_group.make_tidy()
    for i_smx in xrange(p_parent_group.order_p()):
      group_i = sgtbx.space_group()
      group_i.expand_smx(p_parent_group(i_smx))
      for j_smx in xrange(i_smx,p_parent_group.order_p()):
        subgroup = sgtbx.space_group(group_i)
        subgroup.expand_smx(p_parent_group(j_smx))
        subgroup.make_tidy()
        if (subgroup != p_parent_group):
          self._add(subgroup)

  def _add(self, group):
    for g in self._p_groups:
      if (g == group): return 0
    self._p_groups.append(group)
    return 1

  def groups_primitive_setting(self):
    return self._p_groups

  def groups_parent_setting(self):
    result = []
    p2z_op = self.z2p_op.inverse()
    for g in self._p_groups:
      result.append(g.change_basis(p2z_op))
    return result

def show_all():
  for space_group_number in xrange(1,231):
    parent_group_info = sgtbx.space_group_info(space_group_number)
    parent_group_info.show_summary()
    subgrs = subgroups(parent_group_info).groups_parent_setting()
    print "number of subgroups:", len(subgrs)
    for subgroup in subgrs:
      subgroup_info = sgtbx.space_group_info(group=subgroup)
      subgroup_info.show_summary()
    print

if (__name__ == "__main__"):
  show_all()
