
from os.path import join

import numpy as np

from seisflows.tools import unix
from seisflows.tools.array import loadnpy, savenpy
from seisflows.tools.code import loadtxt, savetxt
from seisflows.tools.config import SeisflowsParameters, SeisflowsPaths, \
    ParameterError

from seisflows.tools.math import angle, polyfit2, backtrack2
from seisflows.optimize.lib.LBFGS import LBFGS
from seisflows.optimize.lib.NLCG import NLCG
from seisflows.optimize.lib.io import Writer, StepWriter


PAR = SeisflowsParameters()
PATH = SeisflowsPaths()


class base(object):
    """ Nonlinear optimization base class.

     Available nonlinear optimization algorithms include steepest descent (SD),
     nonlinear conjugate gradient (NLCG), and limited-memory BFGS (LBFGS). 
     Available step control algorithms include a backtracking line search and a
     bracketing line search.

     Though NLCG (a Krylov method) and LBFGS (a quasi-Newton metod) are both 
     widely used for geophysical inversion, LBFGS is more efficient and more
     robust. NLCG requires occasional restarts to avoid numerical stagnation, 
     while LBFGS generally requires few restarts. Restarts are controlled by 
     numerical parameters. Default values provided below should work well 
     for a wide range inversions without the need for manual tuning.

     To reduce memory overhead, vectors are read from disk rather than passed
     from a calling routine. At the start of each search direction computation
     the current model and gradient are read from files 'm_new' and 'g_new';
     the resulting search direction is written to 'p_new'. As the inversion
     progresses, other information is stored to disk as well.
    """

    def check(self):
        """ Checks parameters, paths, and dependencies
        """
        if 'BEGIN' not in PAR:
            raise ParameterError

        if 'END' not in PAR:
            raise ParameterError

        if 'SUBMIT' not in PATH:
            raise ParameterError

        if 'OPTIMIZE' not in PATH:
            setattr(PATH, 'OPTIMIZE', join(PATH.GLOBAL, 'optimize'))

        # search direction algorithm
        if 'SCHEME' not in PAR:
            setattr(PAR, 'SCHEME', 'LBFGS')

        if 'PRECOND' not in PAR:
            setattr(PAR, 'PRECOND', False)

        # line search algorithm
        if 'LINESEARCH' not in PAR:
            if  PAR.SCHEME in ['LBFGS']:
                setattr(PAR, 'LINESEARCH', 'Backtrack')
            else:
                setattr(PAR, 'LINESEARCH', 'Bracket')

        # search direction tuning parameters
        if 'NLCGMAX' not in PAR:
            setattr(PAR, 'NLCGMAX', np.inf)

        if 'NLCGTHRESH' not in PAR:
            setattr(PAR, 'NLCGTHRESH', np.inf)

        if 'LBFGSMEM' not in PAR:
            setattr(PAR, 'LBFGSMEM', 5)

        if 'LBFGSMAX' not in PAR:
            setattr(PAR, 'LBFGSMAX', np.inf)

        if 'LBFGSTHRESH' not in PAR:
            setattr(PAR, 'LBFGSTHRESH', 0.)

        # line search tuning paraemters
        if 'STEPMAX' not in PAR:
            setattr(PAR, 'STEPMAX', 10)

        if 'STEPTHRESH' not in PAR:
            setattr(PAR, 'STEPTHRESH', None)

        if 'STEPINIT' not in PAR:
            setattr(PAR, 'STEPINIT', 0.05)

        if 'STEPFACTOR' not in PAR:
            setattr(PAR, 'STEPFACTOR', 0.5)

        if 'STEPOVERSHOOT' not in PAR:
            setattr(PAR, 'STEPOVERSHOOT', 0.)


    def setup(self):
        """ Sets up nonlinear optimization machinery
        """
        unix.mkdir(PATH.OPTIMIZE)

        # prepare output writers
        self.writer = Writer(
                path=PATH.OUTPUT)

        self.stepwriter = StepWriter(
                path=PATH.SUBMIT)

        # prepare algorithm machinery
        if PAR.SCHEME in ['NLCG']:
            self.NLCG = NLCG(
                path=PATH.OPTIMIZE,
                maxiter=PAR.NLCGMAX,
                thresh=PAR.NLCGTHRESH,
                precond=PAR.PRECOND)

        elif PAR.SCHEME in ['LBFGS']:
            self.LBFGS = LBFGS(
                path=PATH.OPTIMIZE, 
                stepmem=PAR.LBFGSMEM, 
                maxiter=PAR.LBFGSMAX,   
                thresh=PAR.LBFGSTHRESH,
                precond=PAR.PRECOND)

        self.restart = 0
        self.restart_count = 0


     # The following names are used in the 'compute_direction' method and for
     # writing information to disk:
     #    m_new - current model
     #    m_old - previous model
     #    m_try - trial model
     #    f_new - current objective function value
     #    f_old - previous objective function value
     #    f_try - trial objective function value
     #    g_new - current gradient direction
     #    g_old - previous gradient direction
     #    p_new - current search direction
     #    p_old - previous search direction
     #    s_new - current slope along search direction
     #    s_old - previous slope along search direction
     #    alpha - trial step length

    def compute_direction(self):
        """ Computes model update direction from stored gradient
        """
        unix.cd(PATH.OPTIMIZE)

        g_new = loadnpy('g_new')

        if PAR.SCHEME in ['SD']:
            p_new = -g_new

        elif PAR.SCHEME in ['NLCG']:
            p_new, self.restart = self.NLCG()

        elif PAR.SCHEME in ['LBFGS']:
            p_new, self.restart = self.LBFGS()

        # keep track of number of restarts
        if self.restart:
            self.restart_count += 1

        savenpy('p_new', p_new)
        savetxt('s_new', np.dot(g_new, p_new))


    # The following names are used exclusively for the line search:
    #     m - model vector
    #     p - search direction vector
    #     s - slope along search direction
    #     f - value of objective function, evaluated at m
    #     x - step length along search direction
    #     p_ratio - ratio of model norm to search direction norm
    #     s_ratio - ratio of current slope to previous slope

    def initialize_search(self):
        """ Determines initial step length for line search
        """
        unix.cd(PATH.OPTIMIZE)

        m = loadnpy('m_new')
        p = loadnpy('p_new')
        f = loadtxt('f_new')
        norm_m = max(abs(m))
        norm_p = max(abs(p))
        p_ratio = float(norm_m/norm_p)

        # reset search history
        self.search_history = [[0., f]]
        self.step_count = 0
        self.isdone = 0
        self.isbest = 0
        self.isbrak = 0

        # determine initial step length
        if self.iter == 1:
            alpha = p_ratio*PAR.STEPINIT
        elif self.restart:
            alpha = p_ratio*PAR.STEPINIT
        elif PAR.LINESEARCH in ['Backtrack']:
            alpha = 1.
        else:
            alpha = self.step_init()

        # optional ad hoc scaling
        if PAR.STEPOVERSHOOT:
            alpha *= PAR.STEPOVERSHOOT

        # optional maximum step length safegaurd
        if PAR.STEPTHRESH:
            if alpha > p_ratio * PAR.STEPTHRESH and \
                self.iter > 1:
                alpha = p_ratio * PAR.STEPTHRESH

        # write trial model corresponding to chosen step length
        savenpy('m_try', m + p*alpha)
        savetxt('alpha', alpha)

        # upate log
        self.stepwriter(steplen=0., funcval=f)


    def search_status(self):
        """ Determines status of line search

            Maintains line search history by keeping track of step length and
            function value from each trial model evaluation. From line search
            history, determines whether stopping criteria have been satisfied.
        """
        unix.cd(PATH.OPTIMIZE)

        x_ = loadtxt('alpha')
        f_ = loadtxt('f_try')
        if np.isnan(f_):
            raise ValueError

        # update search history
        self.search_history += [[x_, f_]]
        self.step_count += 1
        x = self.step_lens()
        f = self.func_vals()

        # is current step length the best so far?
        vals = self.func_vals(sort=False)
        if np.all(vals[-1] < vals[:-1]):
            self.isbest = 1

        # are stopping criteria satisfied?
        if PAR.LINESEARCH == 'Fixed':
            if any(f[1:] < f[0]) and (f[-2] < f[-1]):
                self.isdone = 1

        elif PAR.LINESEARCH == 'Bracket' or \
           self.iter==1 or self.restart:
            if self.isbrak:
                self.isdone = 1
            elif any(f[1:] < f[0]) and (f[-2] < f[-1]):
                self.isbrak = 1

        elif PAR.LINESEARCH == 'Backtrack':
            if any(f[1:] < f[0]):
                self.isdone = 1

        # update log
        self.stepwriter(steplen=x_, funcval=f_)

        if self.step_count >= PAR.STEPMAX:
            self.isdone = -1
            print ' line search failed [max iter]\n'

        return self.isdone, self.isbest


    def compute_step(self):
        """ Computes next trial step length
        """
        unix.cd(PATH.OPTIMIZE)

        m = loadnpy('m_new')
        p = loadnpy('p_new')
        s = loadtxt('s_new')

        norm_m = max(abs(m))
        norm_p = max(abs(p))
        p_ratio = float(norm_m/norm_p)

        x = self.step_lens()
        f = self.func_vals()

        # compute trial step length
        if PAR.LINESEARCH == 'Fixed':
            alpha = p_ratio*(self.step_count + 1)*PAR.STEPINIT

        elif PAR.LINESEARCH == 'Bracket' or \
            self.iter==1 or self.restart:
            if any(f[1:] < f[0]) and (f[-2] < f[-1]):
                alpha = polyfit2(x, f)
            elif any(f[1:] <= f[0]):
                alpha = loadtxt('alpha')*PAR.STEPFACTOR**-1
            else:
                alpha = loadtxt('alpha')*PAR.STEPFACTOR

        elif PAR.LINESEARCH == 'Backtrack':
            alpha = backtrack2(f[0], s, x[1], f[1], b1=0.1, b2=0.5)

        # write trial model corresponding to chosen step length
        savetxt('alpha', alpha)
        savenpy('m_try', m + p*alpha)


    def finalize_search(self):
        """ Cleans working directory and writes updated model
        """
        unix.cd(PATH.OPTIMIZE)

        m = loadnpy('m_new')
        g = loadnpy('g_new')
        p = loadnpy('p_new')
        s = loadtxt('s_new')

        x = self.step_lens()
        f = self.func_vals()

        # clean working directory
        unix.rm('alpha')
        unix.rm('m_try')
        unix.rm('f_try')

        if self.iter > 1:
            unix.rm('m_old')
            unix.rm('f_old')
            unix.rm('g_old')
            unix.rm('p_old')
            unix.rm('s_old')

        unix.mv('m_new', 'm_old')
        unix.mv('f_new', 'f_old')
        unix.mv('g_new', 'g_old')
        unix.mv('p_new', 'p_old')
        unix.mv('s_new', 's_old')

        # write updated model
        alpha = x[f.argmin()]
        savetxt('alpha', alpha)
        savenpy('m_new', m + p*alpha)
        savetxt('f_new', f.min())

        # append latest output
        self.writer('adhoc', (s/np.dot(p,p)**0.5)**-1 * (f[1]-f[0])/(x[1]-x[0]))
        self.writer('gradient_norm_L1', np.linalg.norm(g, 1))
        self.writer('gradient_norm_L2', np.linalg.norm(g, 2))
        self.writer('misfit', f[0])
        self.writer('restart_count', self.restart_count)
        self.writer('slope', (f[1]-f[0])/(x[1]-x[0]))
        self.writer('step_count', self.step_count)
        self.writer('step_length', x[f.argmin()])
        self.writer('theta', 180.*np.pi**-1*angle(g,p))


    ### line search utilities

    def step_init(self):
        alpha = loadtxt('alpha')
        s_new = loadtxt('s_new')
        s_old = loadtxt('s_old')
        s_ratio = s_new/s_old
        return 2.*s_ratio*alpha


    def step_lens(self, sort=True):
        x, f = zip(*self.search_history)
        x = np.array(x)
        f = np.array(f)
        f_sorted = f[abs(x).argsort()]
        x_sorted = x[abs(x).argsort()]
        if sort:
            return x_sorted
        else:
            return x


    def func_vals(self, sort=True):
        x, f = zip(*self.search_history)
        x = np.array(x)
        f = np.array(f)
        f_sorted = f[abs(x).argsort()]
        x_sorted = x[abs(x).argsort()]
        if sort:
            return f_sorted
        else:
            return f

