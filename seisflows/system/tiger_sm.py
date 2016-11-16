
import sys

from getpass import getuser
from os.path import abspath, exists, join
from uuid import uuid4
from seisflows.tools import unix
from seisflows.config import ParameterError, custom_import

PAR = sys.modules['seisflows_parameters']
PATH = sys.modules['seisflows_paths']


class tiger_sm(custom_import('system', 'slurm_sm')):
    """ Specially designed system interface for tiger.princeton.edu

      See parent class for more information.
    """

    def check(self):
        """ Checks parameters and paths
        """

        if 'UUID' not in PAR:
            setattr(PAR, 'UUID', str(uuid4()))
 
        if 'SCRATCH' not in PATH:
            setattr(PATH, 'SCRATCH', join('/scratch/gpfs', getuser(), 'seisflows', PAR.UUID))

        if 'LOCAL' not in PATH:
            setattr(PATH, 'LOCAL', '')

        super(tiger_sm, self).check()


    def submit(self, *args, **kwargs):
        """ Submits job
        """
        if not exists(PATH.SUBMIT + '/' + 'scratch'):
            unix.ln(PATH.SCRATCH, PATH.SUBMIT + '/' + 'scratch')

        super(tiger_sm, self).submit(*args, **kwargs)
