"""
.. module:: theories.camb

:Synopsis: Managing the CAMB cosmological code
:Author: Jesus Torrado

.. |br| raw:: html

   <br />

This module imports and manages the CAMB cosmological code.

.. note::

   **If you use this cosmological code, please cite it as:**
   |br|
   `A. Lewis, A. Challinor, A. Lasenby, "Efficient computation of CMB anisotropies in closed FRW"
   (arXiv:astro-ph/9911177) <https://arxiv.org/abs/astro-ph/9911177>`_
   |br|
   `C. Howlett, A. Lewis, A. Hall, A. Challinor, "CMB power spectrum parameter degeneracies in the era of precision cosmology"
   (arXiv:1201.3654) <https://arxiv.org/abs/1201.3654>`_


Usage
-----

If you are using a likelihood that requires some observable from CAMB, simply add CAMB
to the theory block.

You can specify any parameter that CAMB understands within the ``theory``
sub-block of the ``params`` block:

.. code-block:: yaml

   theory:
     camb:

   params:
     theory:
       [any param that CAMB understands, fixed, sampled or derived]


Installation
------------

Pre-requisites
^^^^^^^^^^^^^^

**cobaya** calls CAMB using its Python interface, which requires that you compile CAMB
using the GNU gfortran compiler version 4.9 or later. To check if you fulfil that
requisite, type ``gfortran --version`` in the shell, and the first line should look like

.. code::

   GNU Fortran ([your OS version]) [gfortran version] [release date]

Check that ``[gfortran's version]`` is at least 4.9. If you get an error instead, you need
to install gfortran (contact your local IT service).


Automatic installation
^^^^^^^^^^^^^^^^^^^^^^

If you do not plan to modify CAMB, the easiest way to install it is using the
:doc:`automatic installation script <installation_ext>`. Just make sure that
``theory: camb:`` appears in one of the files passed as arguments to the installation
script.


Manual installation (or using your own version)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you are planning to modify CAMB or use an already modified version,
you should not use the automatic installation script. Use the installation method that
best adapts to your needs:

* [**Recommended**]
  To install an up-to-date CAMB locally and use git to keep track of your changes,
  `fork the CAMB repository in Github <https://github.com/cmbant/CAMB>`_
  (follow `this instructions <https://help.github.com/articles/fork-a-repo/>`_) and clone
  it in some folder of your choice, say ``/path/to/theories/CAMB``:

  .. code:: bash
     
      $ cd /path/to/theories/
      $ git clone https://[YourGithubUser]@github.com/[YourGithubUser]/CAMB.git
      $ cd CAMB
      $ make
     
* To install an up-to-date CAMB locally, if you don't care about keeping track of your
  changes (and don't want to use ``git``), do:

  .. code:: bash

      $ cd /path/to/theories/
      $ wget https://github.com/cmbant/CAMB/archive/master.zip
      $ unzip master.zip
      $ rm master.zip
      $ mv CAMB-master CAMB       
      $ cd CAMB
      $ make

* To use your own version, assuming it's placed under ``/path/to/theories/CAMB``,
  just make sure it is compiled (and that the version on top of which you based your
  modifications is old enough to have the ``pycamb`` interface implemented.

In the three cases above, you **must** specify the path to your CAMB installation in
the input block for CAMB (otherwise a system-wide CAMB may be used instead):

.. code:: yaml

   theory:
     camb:
       path: /path/to/theories/CAMB

.. note::

   In any of these methods, you should **not** install CAMB as python package using
   ``python setup.py install --user``, as the official instructions suggest.
   It is actually safer not to do so if you intend to switch between different versions or
   modifications of CAMB.


Modifying CAMB
--------------

If you modify CAMB and add new variables, you don't need to let **cobaya** now,
but make sure
that the variables you create are exposed in its Python interface (contact CAMB's
developers if you need help with that).

.. todo::

   Point somewhere to the CAMB documentation where how to make these modifications
   is explained.

"""

# Python 2/3 compatibility
from __future__ import absolute_import
from __future__ import division

# Global
import sys
import os
from copy import deepcopy
import numpy as np

# Local
from cobaya.theory import Theory
from cobaya.log import HandledException

# Logger
import logging
log = logging.getLogger(__name__)


class camb(Theory):

    def initialise(self):
        """Importing CAMB from the correct path, if given."""
        if self.path:
            log.info("Importing *local* CAMB from "+self.path)
            if not os.path.exists(self.path):
                log.error("The given folder does not exist: '%s'", self.path)
                raise HandledException
            pycamb_path = os.path.join(self.path, "pycamb")
            if not os.path.exists(pycamb_path):
                log.error("Either CAMB is not in the given folder, '%s', or you are "
                          "using a very old version without the `pycamb` Python interface.",
                          self.path)
                raise HandledException
            sys.path.insert(0, pycamb_path)
        else:
            log.info("Importing *global* CAMB.")
        try:
            import camb
        except ImportError:
            log.error(
                "Couldn't find the CAMB python interface.\n"
                "Make sure that you have compiled it, and that you either\n"
                " (a) specify a path (you didn't) or\n"
                " (b) install the Python interface globally with\n"
                "     '/path/to/camb/pycamb/python setup.py install --user'")
            raise HandledException
        self.camb = camb
        # Generate states, to avoid recomputing
        self.n_states = 3
        self.states = [{"CAMBparams": None, "CAMBresults": None, "powers": None, 
                        "params": None, "derived": None, "last": 0}
                       for i in range(self.n_states)]
        # patch: if cosmomc_theta is used, CAMB needs to be passed explicitly "H0=None"
        if (all((p in self.sampled_params()) for p in ["H0", "cosmomc_theta"]) or
            all((p in self.fixed) for p in ["H0", "cosmomc_theta"])):
            log.error("Can't fix or sample simultaneously both H0 and cosmomc_theta.")
            raise HandledException
        if "cosmomc_theta" in self.fixed or "cosmomc_theta" in self.sampled_params():
            self.fixed["H0"] = None

    def current_state(self):
       lasts = [self.states[i]["last"] for i in range(self.n_states)]
       return self.states[lasts.index(max(lasts))]

    def set(self, params_values_dict, i_state):
        # Feed the arguments defining the cosmology to the cosmological code
        # Fixed
        args = self.fixed
        # Sampled -- save the state for avoiding recomputing later
        args.update(params_values_dict)
        # Precision (fixed at the theory block level)
        args.update(self.precision)
        # Generate and save
        log.debug("Setting parameters: %r", args)
        self.states[i_state]["params"] = params_values_dict
        try:
            self.states[i_state]["CAMBparams"] = self.camb.set_params(**args)
        except Exception:
            log.error("Error setting CAMB parameters -- see CAMB's error trace below.\n"
                      "The parameters were %r", args)
            raise

    def compute(self, derived=None, **params_values_dict):
        lasts = [self.states[i]["last"] for i in range(self.n_states)]
        try:
            # are the parameter values there already?
            i_state = (i for i in range(self.n_states)
                       if self.states[i]["params"] == params_values_dict).next()
            # Get (pre-computed) derived parameters
            if derived == {}:
                derived.update(dict([[p,v] for p,v in
                                     zip(self.derived, self.states[i_state]["derived"])]))
            log.debug("Re-using computed results (state %d)", i_state)
        except StopIteration:
            # update the (first) oldest one and compute
            i_state = lasts.index(min(lasts))
            log.debug("Computing (state %d)", i_state)
            self.set(params_values_dict, i_state)
            # Compute the necessary products
            self.states[i_state]["CAMBresults"] = \
                self.camb.get_results(self.states[i_state]["CAMBparams"])
            self.states[i_state]["powers"] = \
                self.states[i_state]["CAMBresults"].get_cmb_power_spectra(
                    self.states[i_state]["CAMBparams"])
            # Prepare derived parameters
            if derived == {}:
                self.get_derived(derived, i_state)
                # Careful: next step must keep the order
                self.states[i_state]["derived"] = [derived[p] for p in self.derived]
        # make this one the current one by decreasing the antiquity of the rest
        for i in range(self.n_states):
            self.states[i]["last"] -= max(lasts)
        self.states[i_state]["last"] = 1

    def needs(self, arguments):
        for k,v in arguments.items():
            if k == "l_max":
                # Take the max of the requested ones
                self.fixed["lmax"] = max(v,self.fixed.get("lmax",0))
            elif k == "Cl":
#####                print "TODO: better specification of Cl's for CAMB!!!"
                pass
            else:
                log.error("'%s' does not understand the requirement '%s:%s'.",
                          self.__class__.__name__,k,v)
                raise HandledException

    def get_derived(self, derived, i_state):
        """Populates a dictionary of derived parameters with their values, using the
        state #`i_state`."""
        for p in self.derived:
#            print "Derived: ",p," --> ",
            # needs standard way to get derived parameters!
#            print self.states[i_state]["CAMBparams"].Reion
            derived[p] = getattr(self.states[i_state]["CAMBparams"], p)
            
#            if derived[p] is not None: print "OK: 1"
            if derived[p] == None:
                log.error("Derived param '%s' not implemented in the CAMB interface", p)
                raise HandledException

    def get_cl(self):
        """
        Returns the power spectra in microK^2.
        """
        current_state = self.current_state()
        # get C_l^XX from the cosmological code
        cl_camb = deepcopy(current_state["powers"]["total"])
        cl = {"ell": np.arange(cl_camb.shape[0]),
              "tt": cl_camb[:,0], "te": cl_camb[:,3], "ee": cl_camb[:,1], "bb":cl_camb[:,2]}
        # convert dimensionless C_l's to C_l in muK**2
        T = current_state["CAMBparams"].TCMB
        ell_factor = cl["ell"]*(cl["ell"]+1)/(2*np.pi)
        for key in cl.iterkeys():
            if key not in ['pp', 'ell']:
                cl[key][2:] = cl[key][2:] /ell_factor[2:] *(T*1.e6)**2
        return cl


# Installation routines ###################################################################

def is_installed(**kwargs):
    try:
        import camb
    except:
        return False
    return True

def install(force=False, **kwargs):
    import os
    import pip
    exit_status = pip.main(["install", "camb", "--upgrade"]+
                           (["--user"] if not "TRAVIS" in os.environ else [])+
                           (["--force-reinstall"] if force else []))
    if exit_status:
        return False
    return True
