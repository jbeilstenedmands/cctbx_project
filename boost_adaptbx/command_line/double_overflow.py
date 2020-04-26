from __future__ import absolute_import, division, print_function

# LIBTBX_SET_DISPATCHER_NAME boost_adaptbx.double_overflow

import boost_adaptbx.python
import sys

def run(args):
  assert len(args) == 0
  sizeof_double = boost_adaptbx.python.c_sizeof("double")
  assert sizeof_double == 8
  x = 1.e300
  y = 1.e200
  print("Now multiplying double values %g * %g ..." % (x, y))
  sys.stdout.flush()
  result = boost_adaptbx.python.ext.multiply_doubles(x, y)
  print("Result:", result)

if (__name__ == "__main__"):
  run(sys.argv[1:])
