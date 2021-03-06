import numpy as np
from itertools import combinations
import bisect

from sklearn.cluster import KMeans
from sklearn import datasets
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score as sil
import util


class ConsensusCluster:
    """
      Implementation of Consensus clustering, following the paper
      https://link.springer.com/content/pdf/10.1023%2FA%3A1023949509487.pdf
      Args:
        * cluster -> clustering class
        * NOTE: the class is to be instantiated with parameter `n_clusters`,
          and possess a `fit_predict` method, which is invoked on data.
        * L -> smallest number of clusters to try
        * K -> biggest number of clusters to try
        * H -> number of resamplings for each cluster number
        * resample_proportion -> percentage to sample
        * Mk -> consensus matrices for each k (shape =(K,data.shape[0],data.shape[0]))
                (NOTE: every consensus matrix is retained, like specified in the paper)
        * Ak -> area under CDF for each number of clusters
                (see paper: section 3.3.1. Consensus distribution.)
        * deltaK -> changes in areas under CDF
                (see paper: section 3.3.1. Consensus distribution.)
        * self.bestK -> number of clusters that was found to be best
      """

    def __init__(self, cluster, L, K, H, resample_proportion=0.5):
        assert 0 <= resample_proportion <= 1, "proportion has to be between 0 and 1"
        self.cluster_ = cluster
        self.resample_proportion_ = resample_proportion
        self.L_ = L
        self.K_ = K
        self.H_ = H
        self.Mk = None
        self.Ak = None
        self.deltaK = None
        self.bestK = None

    def fit(self, data, verbose=False):
        """
        Fits a consensus matrix for each number of clusters
        Args:
          * data -> (examples,attributes) format
          * verbose -> should print or not
        """
        N = data.shape[0]  # number of points
        Mk = np.zeros((self.K_ - self.L_, N, N))
        Is = np.zeros(
            (N, N))  # counter for each pair of points if they were used in resample data for current number of clusters
        for k in range(self.L_, self.K_):  # for each number of clusters
            i_ = k - self.L_
            if verbose:
                print("At k = %d, aka. iteration = %d" % (k, i_))
            for h in range(self.H_):  # resample H times
                if verbose:
                    print("\tAt resampling h = %d, (k = %d)" % (h, k))
                resampled_indices, resample_data = util.resample(data, self.resample_proportion_)
                Mh = self.cluster_(n_clusters=k).fit_predict(resample_data)
                # find indexes of elements from same clusters with bisection
                # on sorted array => this is more efficient than brute force search
                id_clusts = np.argsort(Mh)
                sorted_ = Mh[id_clusts]  # 0000000000111111111111222222
                for i in range(k):  # for each cluster
                    ia = bisect.bisect_left(sorted_, i)
                    ib = bisect.bisect_right(sorted_, i)
                    cluster_indices = id_clusts[ia:ib]
                    is_ = resampled_indices[cluster_indices]
                    ids_ = np.array(list(combinations(is_, 2))).T  # get all pairs of i-th cluster
                    # sometimes only one element is in a cluster (no combinations)
                    if ids_.size != 0:
                        Mk[i_, ids_[0], ids_[1]] += 1
                # increment counts
                ids_2 = np.array(list(combinations(resampled_indices, 2))).T
                Is[ids_2[0], ids_2[1]] += 1
            Is += Is.T
            Mk[i_] /= Is + 1e-8  # consensus matrix
            Mk[i_] += Mk[i_].T  # Mk[i_] is upper triangular (with zeros on diagonal), we now make it symmetric
            Mk[i_] += np.eye(N)
            # Mk[i_, range(N), range(N)] = 1  # always with self, fill the diag
            Is.fill(0)  # reset counter
        self.Mk = Mk

        # fits areas under the CDFs
        self.Ak = np.zeros(self.K_ - self.L_)
        for i, m in enumerate(Mk):
            hist, bins = np.histogram(m.ravel(), density=True)
            self.Ak[i] = np.sum(h * (b - a)
                                for b, a, h in zip(bins[1:], bins[:-1], np.cumsum(hist)))

        # fits differences between areas under CDFs
        self.deltaK = np.array([(Ab - Aa) / Aa if i > 2 else Aa
                                for Ab, Aa, i in zip(self.Ak[1:], self.Ak[:-1], range(self.L_, self.K_ - 1))])
        self.bestK = np.argmax(self.deltaK) + \
                     self.L_ if self.deltaK.size > 0 else self.L_

    def fit_from_cfg(self, data):
        self.X = data
        N = data.shape[0]  # number of points
        Mk = np.zeros((N, N))
        Is = np.zeros(
            (N, N))  # counter for each pair of points if they were used in resample data for current number of clusters

        for h in range(self.H_):  # resample H times
            resampled_indices, resample_data = util.resample(data, self.resample_proportion_)
            self.cluster_.fit(resample_data)
            if hasattr(self.cluster_, 'predict'):
                Mh = self.cluster_.predict(resample_data)
            else:
                Mh = self.cluster_.labels_

            id_clusts = np.argsort(Mh)
            sorted_ = Mh[id_clusts]  # 0000000000111111111111222222

            k = len(np.unique(sorted_))

            for i in range(k):  # for each cluster
                ia = bisect.bisect_left(sorted_, i)
                ib = bisect.bisect_right(sorted_, i)
                cluster_indices = id_clusts[ia:ib]
                is_ = resampled_indices[cluster_indices]
                ids_ = np.array(list(combinations(is_, 2))).T  # get all pairs of i-th cluster
                # sometimes only one element is in a cluster (no combinations)
                if ids_.size != 0:
                    Mk[ids_[0], ids_[1]] += 1
            # increment counts
            ids_2 = np.array(list(combinations(resampled_indices, 2))).T
            Is[ids_2[0], ids_2[1]] += 1
        Is += Is.T
        Mk /= Is + 1e-8  # consensus matrix
        Mk += Mk.T  # Mk[i_] is upper triangular (with zeros on diagonal), we now make it symmetric
        Mk += np.eye(N)
        Is.fill(0)  # reset counter
        self.Mk = Mk

    def predict(self):
        """
        Predicts on the consensus matrix, for best found cluster number
        """
        assert self.Mk is not None, "First run fit"
        return self.cluster_(n_clusters=self.bestK).fit_predict(
            1 - self.Mk[self.bestK - self.L_])

    def predict_hierarchical(self):
        assert self.Mk is not None, "First run fit"
        cls = AgglomerativeClustering(n_clusters=self.bestK, linkage="complete", affinity='precomputed').fit(
            1 - self.Mk[self.bestK - self.L_]
        )
        return cls.labels_

    def predict_from_tuned(self):
        """Returns labels from hierarchical clustering with n_clusters that maximizes Silhouette measure"""
        assert self.Mk is not None, "First run fit"
        scores = []
        labels = []

        for k in range(self.L_, self.K_):
            cls = AgglomerativeClustering(n_clusters=k, linkage='average', affinity='precomputed').fit(1 - self.Mk)

            ls = cls.labels_
            labels.append(ls)
            scores.append(sil(self.X, ls))

        labels = np.array(labels)
        return labels[np.argmax(scores)]

    def predict_data(self, data):
        """
        Predicts on the data, for best found cluster number
        Args:
          * data -> (examples,attributes) format
        """
        assert self.Mk is not None, "First run fit"
        return self.cluster_(n_clusters=self.bestK).fit_predict(
            data)


if __name__ == "__main__":
    data, y_true = datasets.make_blobs(200, centers=2, shuffle=True, random_state=42)
    cls = ConsensusCluster(KMeans, 2, 5, 5)
    cls.fit(data, verbose=True)
    print(cls.predict())
    print(y_true)
