import numpy as np

def convex_cone(data, latents):
    """do maximum projection of the data"""

    data = data.copy()
    res = {'base': [], 'timecourses': []}

    for i in range(latents):

        # most interesting column
        col_concern = np.max(data, axis=0)
        best_col = np.argmax(col_concern)

        timecourse = data[:, best_col].copy()
        norm = np.dot(timecourse, timecourse)
        timecourse /= np.sqrt(norm)
        base = np.dot(data.T, timecourse)
        base[base < 0] = 0

        data -= np.outer(timecourse, base)

        res['base'].append(base)
        res['timecourses'].append(timecourse)

    return res


NORMS = {'global_sparse': lambda new_vec, x: np.sum(x, 0),
         'local_sparse': lambda new_vec, x: 1}

class regHALS(object):

    def __init__(self, num_comp, **kwargs):
        self.k = num_comp
        self.maxcount = kwargs.get('maxcount', 100)
        self.eps = kwargs.get('eps', 1E-5)
        self.verbose = kwargs.get('verbose', 0)
        self.shape = kwargs.get('shape', None)
        self.init = kwargs.get('init', 'convex')
        self.smooth_param = kwargs.get('smooth_param', 0)
        self.sparse_param = kwargs.get("sparse_param", 0)
        self.neg_time = kwargs.get("neg_time", False)
        self.timenorm = kwargs.get('timenorm', lambda x: np.sqrt(np.dot(x, x)))
        self.basenorm = kwargs.get("basenorm", lambda x:1)
        self.sparse_fct = NORMS[kwargs.get("sparse_fct", 'global_sparse')]


    def frob_dist(self, Y, A, X):
        """ frobenius distance between Y and A X """
        return np.linalg.norm(Y - np.dot(A, X))

    def init_factors(self, Y):
        """ generate start matrices U, V """

        if self.init == 'random':
            m, n = Y.shape
            A = np.random.rand(m, self.k)
            X = np.ones((self.k, n))

            AX = np.dot(A, X).flatten()
            alpha = np.dot(Y.flatten(), AX) / np.dot(AX, AX)
            A /= np.sqrt(np.abs(alpha) + 1E-10)
            X /= np.sqrt(np.abs(alpha) + 1E-10)
        elif self.init == 'convex':
            out = convex_cone(Y, self.k)
            X = np.array(out['base'])
            A = np.array(out['timecourses']).T
        return A, X

    def create_nn_matrix(self):
        nn_matrix = []
        for i in range(self.shape[0]):
            for j in range(self.shape[1]):
                temp = np.zeros(self.shape)
                if i > 0:
                    temp[i - 1, j] = 1
                if i < self.shape[0] - 1:
                    temp[i + 1, j] = 1
                if j > 0:
                    temp[i, j - 1] = 1
                if j < self.shape[1] - 1:
                    temp[i, j + 1] = 1
                nn_matrix.append(1.*temp.flatten() / np.sum(temp))
        return np.array(nn_matrix)


    def fit(self, Y):

        self.psi = 1E-12 # numerical stabilization
        YT = Y.T

        A, X = self.init_factors(Y)
        # create neighborhodd matrix
        if self.smooth_param:
            self.S = self.create_nn_matrix()

        count = 0
        obj_old = 1e99
        nrm_Y = np.linalg.norm(Y)

        if self.verbose:
            print 'init completed'

        while True:
            if count >= self.maxcount: break
            A, X = self.update(Y, YT, A, X)

            if np.any(np.isnan(A)) or np.any(np.isinf(A)) or \
               np.any(np.isnan(X)) or np.any(np.isinf(X)):

                if self.verbose: print "RESTART"
                A, X = self.init_factors(Y, self.k)
                count = 0

            count += 1

            # relative distance which is independeant to scaling of A
            obj = self.frob_dist(Y, A, X) / nrm_Y

            delta_obj = obj - obj_old
            if self.verbose:
                if count % self.verbose == 0:
                    print "count=%6d obj=%E d_obj=%E" % (count, obj, delta_obj)


            # delta_obj should be "almost negative" and small enough:
            if -self.eps < delta_obj <= 0:
                break

            obj_old = obj


        if self.verbose:
            print "FINISHED:"
            print "count=%6d obj=%E d_obj=%E" % (count, obj, delta_obj)

        return A, X, obj

    def update(self, Y, YT, A, X):

        E = Y - np.dot(A, X)
        for j in range(A.shape[1]):

            aj = A[:, j]
            xj = X[j, :]

            Rt = E + np.outer(aj, xj)

            xj = self.project_residuen(Rt.T, j, aj, self.sparse_param, self.smooth_param,
                                       X=X, sparse_fct=self.sparse_fct)
            xj /= self.basenorm(xj) + self.psi

            aj = self.project_residuen(Rt, j, xj, rectify=not(self.neg_time), X=A.T)
            aj /= self.timenorm(aj) + self.psi

            Rt -= np.outer(aj, xj)

            A[:, j] = aj
            X[j, :] = xj

            E = Rt

        return A, X

    def project_residuen(self, res, oldind, to_base, sparse_param=0,
                         smoothness=0, rectify=True, X=0, sparse_fct=''):

        new_vec = np.dot(res, to_base)

        if sparse_param > 0:
            mask = np.ones(X.shape[0]).astype('bool')
            mask[oldind] = False
            occupation = sparse_fct(new_vec, X[mask])
            new_vec -= sparse_param * occupation

        if smoothness > 0:
            new_vec += smoothness * np.dot(self.S, X[oldind])

        new_vec /= (np.linalg.norm(to_base) ** 2 + self.psi + smoothness)
        if rectify:
            new_vec[new_vec < 0] = 0

        return new_vec
