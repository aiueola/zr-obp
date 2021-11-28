# Copyright (c) Yuta Saito, Yusuke Narita, and ZOZO Technologies, Inc. All rights reserved.
# Licensed under the Apache 2.0 License.

"""Off-Policy Estimators."""
from abc import ABCMeta
from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict
from typing import Optional

import numpy as np
from sklearn.utils import check_scalar

from ..utils import check_array
from ..utils import check_ope_inputs
from ..utils import estimate_confidence_interval_by_bootstrap
from .helper import estimate_bias_in_ope
from .helper import estimate_high_probability_upper_bound_bias


@dataclass
class BaseOffPolicyEstimator(metaclass=ABCMeta):
    """Base class for OPE estimators."""

    @abstractmethod
    def _estimate_round_rewards(self) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards."""
        raise NotImplementedError

    @abstractmethod
    def estimate_policy_value(self) -> float:
        """Estimate the policy value of evaluation policy."""
        raise NotImplementedError

    @abstractmethod
    def estimate_interval(self) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure."""
        raise NotImplementedError


@dataclass
class ReplayMethod(BaseOffPolicyEstimator):
    """Relpay Method (RM).

    Note
    -------
    Replay Method (RM) estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{RM}} (\\pi_e; \\mathcal{D}) :=
        \\frac{\\mathbb{E}_{\\mathcal{D}}[\\mathbb{I} \\{ \\pi_e (x_t) = a_t \\} r_t ]}{\\mathbb{E}_{\\mathcal{D}}[\\mathbb{I} \\{ \\pi_e (x_t) = a_t \\}]},

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`\\pi_e: \\mathcal{X} \\rightarrow \\mathcal{A}` is the function
    representing action choices by the evaluation policy realized during offline bandit simulation.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.

    Parameters
    ----------
    estimator_name: str, default='rm'.
        Name of the estimator.

    References
    ------------
    Lihong Li, Wei Chu, John Langford, and Xuanhui Wang.
    "Unbiased Offline Evaluation of Contextual-bandit-based News Article Recommendation Algorithms.", 2011.

    """

    estimator_name: str = "rm"

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ------------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (must be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like, shape (n_rounds,)
            Rewards of each round estimated by the Replay Method.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        action_match = np.array(
            action_dist[np.arange(action.shape[0]), action, position] == 1
        )
        estimated_rewards = np.zeros_like(action_match)
        if action_match.sum() > 0.0:
            estimated_rewards = action_match * reward / action_match.mean()
        return estimated_rewards

    def estimate_policy_value(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> float:
        """Estimate the policy value of evaluation policy.

        Parameters
        ------------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (must be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        V_hat: float
            Estimated policy value (performance) of a given evaluation policy.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        check_ope_inputs(
            action_dist=action_dist, position=position, action=action, reward=reward
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        return self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            action_dist=action_dist,
        ).mean()

    def estimate_interval(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        alpha: float = 0.05,
        n_bootstrap_samples: int = 100,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (must be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        alpha: float, default=0.05
            Significance level.

        n_bootstrap_samples: int, default=10000
            Number of resampling performed in the bootstrap procedure.

        random_state: int, default=None
            Controls the random seed in bootstrap sampling.

        Returns
        ----------
        estimated_confidence_interval: Dict[str, float]
            Dictionary storing the estimated mean and upper-lower confidence bounds.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        check_ope_inputs(
            action_dist=action_dist, position=position, action=action, reward=reward
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        estimated_round_rewards = self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            action_dist=action_dist,
        )
        return estimate_confidence_interval_by_bootstrap(
            samples=estimated_round_rewards,
            alpha=alpha,
            n_bootstrap_samples=n_bootstrap_samples,
            random_state=random_state,
        )


@dataclass
class InverseProbabilityWeighting(BaseOffPolicyEstimator):
    """Inverse Probability Weighting (IPW) Estimator.

    Note
    -------
    Inverse Probability Weighting (IPW) estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{IPW}} (\\pi_e; \\mathcal{D}) := \\mathbb{E}_{\\mathcal{D}} [ w(x_t,a_t) r_t],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    When the weight-clipping is applied, a large importance weight is clipped as :math:`\\hat{w}(x,a) := \\min \\{ \\lambda, w(x,a) \\}`
    where :math:`\\lambda (>0)` is a hyperparameter that decides a maximum allowed importance weight.

    IPW re-weights the rewards by the ratio of the evaluation policy and behavior policy (importance weight).
    When the behavior policy is known, IPW is unbiased and consistent for the true policy value.
    However, it can have a large variance, especially when the evaluation policy significantly deviates from the behavior policy.

    Parameters
    ------------
    lambda_: float, default=np.inf
        A maximum possible value of the importance weight.
        When a positive finite value is given, importance weights larger than `lambda_` will be clipped.

    estimator_name: str, default='ipw'.
        Name of the estimator.

    use_estimated_pscore: bool, default=False.
        If True, estimated_pscore is used to estimate policy values.
        If False, pscore is used to estimate policy values.

    References
    ------------
    Alex Strehl, John Langford, Lihong Li, and Sham M Kakade.
    "Learning from Logged Implicit Exploration Data"., 2010.

    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    Yi Su, Maria Dimakopoulou, Akshay Krishnamurthy, and Miroslav Dudik.
    "Doubly Robust Off-Policy Evaluation with Shrinkage.", 2020.

    """

    lambda_: float = np.inf
    estimator_name: str = "ipw"
    use_estimated_pscore: bool = False

    def __post_init__(self) -> None:
        """Initialize Class."""
        check_scalar(
            self.lambda_,
            name="lambda_",
            target_type=(int, float),
            min_val=0.0,
        )
        if self.lambda_ != self.lambda_:
            raise ValueError("lambda_ must not be nan")
        if not isinstance(self.use_estimated_pscore, bool):
            raise TypeError(
                f"`use_estimated_pscore` must be a bool, but {type(self.use_estimated_pscore)} is given"
            )

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like or Tensor, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by IPW.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        iw = action_dist[np.arange(action.shape[0]), action, position] / pscore
        # weight clipping
        if isinstance(iw, np.ndarray):
            iw = np.minimum(iw, self.lambda_)
        return reward * iw

    def estimate_policy_value(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: Optional[np.ndarray],
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        estimated_pscore: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate the policy value of evaluation policy.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,), can be None
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.
            If self.use_estimated_pscore is False, pscore must not be None.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        estimated_pscore: array-like, shape (n_rounds,), default=None
            Estimated value of action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\hat{\\pi}_b(a_t|x_t)`.
            If self.use_estimated_pscore is True, estimated_pscore must not be None.

        Returns
        ----------
        V_hat: float
            Estimated policy value (performance) of a given evaluation policy.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        if self.use_estimated_pscore:
            check_array(array=estimated_pscore, name="estimated_pscore", expected_dim=1)
            pscore_ = estimated_pscore
        else:
            check_array(array=pscore, name="pscore", expected_dim=1)
            pscore_ = pscore

        check_ope_inputs(
            action_dist=action_dist,
            position=position,
            action=action,
            reward=reward,
            pscore=pscore_,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        return self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            pscore=pscore_,
            action_dist=action_dist,
        ).mean()

    def estimate_interval(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        estimated_pscore: Optional[np.ndarray] = None,
        alpha: float = 0.05,
        n_bootstrap_samples: int = 10000,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,), can be None
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.
            If self.use_estimated_pscore is False, pscore must not be None.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        estimated_pscore: array-like, shape (n_rounds,), default=None
            Estimated value of action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\hat{\\pi}_b(a_t|x_t)`.
            If self.use_estimated_pscore is True, estimated_pscore must not be None.

        alpha: float, default=0.05
            Significance level.

        n_bootstrap_samples: int, default=10000
            Number of resampling performed in the bootstrap procedure.

        random_state: int, default=None
            Controls the random seed in bootstrap sampling.

        Returns
        ----------
        estimated_confidence_interval: Dict[str, float]
            Dictionary storing the estimated mean and upper-lower confidence bounds.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        if self.use_estimated_pscore:
            check_array(array=estimated_pscore, name="estimated_pscore", expected_dim=1)
            pscore_ = estimated_pscore
        else:
            check_array(array=pscore, name="pscore", expected_dim=1)
            pscore_ = pscore

        check_ope_inputs(
            action_dist=action_dist,
            position=position,
            action=action,
            reward=reward,
            pscore=pscore_,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        estimated_round_rewards = self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            pscore=pscore_,
            action_dist=action_dist,
        )
        return estimate_confidence_interval_by_bootstrap(
            samples=estimated_round_rewards,
            alpha=alpha,
            n_bootstrap_samples=n_bootstrap_samples,
            random_state=random_state,
        )

    def _estimate_mse_score(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        use_bias_upper_bound: bool = True,
        delta: float = 0.05,
        **kwargs,
    ) -> float:
        """Estimate the MSE score of a given clipping hyperparameter to conduct hyperparameter tuning.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        use_bias_upper_bound: bool, default=True
            Whether to use bias upper bound in hyperparameter tuning.
            If False, direct bias estimator is used to estimate the MSE.

        delta: float, default=0.05
            A confidence delta to construct a high probability upper bound based on the Bernstein’s inequality.

        Returns
        ----------
        estimated_mse_score: float
            Estimated MSE score of a given clipping hyperparameter `lambda_`.
            MSE score is the sum of (high probability) upper bound of bias and the sample variance.
            This is estimated using the automatic hyperparameter tuning procedure
            based on Section 5 of Su et al.(2020).

        """
        n_rounds = reward.shape[0]
        # estimate the sample variance of IPW with clipping
        sample_variance = np.var(
            self._estimate_round_rewards(
                reward=reward,
                action=action,
                pscore=pscore,
                action_dist=action_dist,
                position=position,
            )
        )
        sample_variance /= n_rounds

        # estimate the (high probability) upper bound of the bias of IPW with clipping
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        if use_bias_upper_bound:
            bias_term = estimate_high_probability_upper_bound_bias(
                reward=reward, iw=iw, iw_hat=np.minimum(iw, self.lambda_), delta=delta
            )
        else:
            bias_term = estimate_bias_in_ope(
                reward=reward,
                iw=iw,
                iw_hat=np.minimum(iw, self.lambda_),
            )
        estimated_mse_score = sample_variance + (bias_term ** 2)

        return estimated_mse_score


@dataclass
class SelfNormalizedInverseProbabilityWeighting(InverseProbabilityWeighting):
    """Self-Normalized Inverse Probability Weighting (SNIPW) Estimator.

    Note
    -------
    Self-Normalized Inverse Probability Weighting (SNIPW) estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{SNIPW}} (\\pi_e; \\mathcal{D}) :=
        \\frac{\\mathbb{E}_{\\mathcal{D}} [w(x_t,a_t) r_t]}{ \\mathbb{E}_{\\mathcal{D}} [w(x_t,a_t)]},

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.

    SNIPW re-weights the observed rewards by the self-normalized importance weihgt.
    This estimator is not unbiased even when the behavior policy is known.
    However, it is still consistent for the true policy value and increases the stability in some senses.
    See the references for the detailed discussions.

    Parameters
    ----------
    estimator_name: str, default='snipw'.
        Name of the estimator.

    References
    ----------
    Adith Swaminathan and Thorsten Joachims.
    "The Self-normalized Estimator for Counterfactual Learning.", 2015.

    Nathan Kallus and Masatoshi Uehara.
    "Intrinsically Efficient, Stable, and Bounded Off-Policy Evaluation for Reinforcement Learning.", 2019.

    """

    estimator_name: str = "snipw"

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like or Tensor, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by the SNIPW estimator.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        iw = action_dist[np.arange(action.shape[0]), action, position] / pscore
        return reward * iw / iw.mean()


@dataclass
class DirectMethod(BaseOffPolicyEstimator):
    """Direct Method (DM).

    Note
    -------
    DM first learns a supervised machine learning model, such as ridge regression and gradient boosting,
    to estimate the mean reward function (:math:`q(x,a) = \\mathbb{E}[r|x,a]`).
    It then uses it to estimate the policy value as follows.

    .. math::

        \\hat{V}_{\\mathrm{DM}} (\\pi_e; \\mathcal{D}, \\hat{q})
        &:= \\mathbb{E}_{\\mathcal{D}} \\left[ \\sum_{a \\in \\mathcal{A}} \\hat{q} (x_t,a) \\pi_e(a|x_t) \\right],    \\\\
        & =  \\mathbb{E}_{\\mathcal{D}}[\\hat{q} (x_t,\\pi_e)],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    :math:`\\hat{q} (x,a)` is an estimated expected reward given :math:`x` and :math:`a`.
    :math:`\\hat{q} (x_t,\\pi):= \\mathbb{E}_{a \\sim \\pi(a|x)}[\\hat{q}(x,a)]` is the expectation of the estimated reward function over :math:`\\pi`.
    To estimate the mean reward function, please use `obp.ope.regression_model.RegressionModel`, which supports several fitting methods specific to OPE.

    If the regression model (:math:`\\hat{q}`) is a good approximation to the true mean reward function,
    this estimator accurately estimates the policy value of the evaluation policy.
    If the regression function fails to approximate the mean reward function well,
    however, the final estimator is no longer consistent.

    Parameters
    ----------
    estimator_name: str, default='dm'.
        Name of the estimator.

    References
    ----------
    Alina Beygelzimer and John Langford.
    "The offset tree for learning with partial labels.", 2009.

    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    """

    estimator_name: str = "dm"

    def _estimate_round_rewards(
        self,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate the policy value of evaluation policy.

        Parameters
        ----------
        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by the DM estimator.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        n_rounds = position.shape[0]
        q_hat_at_position = estimated_rewards_by_reg_model[
            np.arange(n_rounds), :, position
        ]
        pi_e_at_position = action_dist[np.arange(n_rounds), :, position]

        if isinstance(action_dist, np.ndarray):
            return np.average(
                q_hat_at_position,
                weights=pi_e_at_position,
                axis=1,
            )
        else:
            raise ValueError("action must be 1D array")

    def estimate_policy_value(
        self,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> float:
        """Estimate the policy value of evaluation policy.

        Parameters
        ----------
        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        V_hat: float
            Estimated policy value (performance) of a given evaluation policy.

        """
        check_array(
            array=estimated_rewards_by_reg_model,
            name="estimated_rewards_by_reg_model",
            expected_dim=3,
        )
        check_ope_inputs(
            action_dist=action_dist,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
            position=position,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        return self._estimate_round_rewards(
            position=position,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
            action_dist=action_dist,
        ).mean()

    def estimate_interval(
        self,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        alpha: float = 0.05,
        n_bootstrap_samples: int = 10000,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure.

        Parameters
        ----------
        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        alpha: float, default=0.05
            Significance level.

        n_bootstrap_samples: int, default=10000
            Number of resampling performed in the bootstrap procedure.

        random_state: int, default=None
            Controls the random seed in bootstrap sampling.

        Returns
        ----------
        estimated_confidence_interval: Dict[str, float]
            Dictionary storing the estimated mean and upper-lower confidence bounds.

        """
        check_array(
            array=estimated_rewards_by_reg_model,
            name="estimated_rewards_by_reg_model",
            expected_dim=3,
        )
        check_ope_inputs(
            action_dist=action_dist,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
            position=position,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        estimated_round_rewards = self._estimate_round_rewards(
            position=position,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
            action_dist=action_dist,
        )
        return estimate_confidence_interval_by_bootstrap(
            samples=estimated_round_rewards,
            alpha=alpha,
            n_bootstrap_samples=n_bootstrap_samples,
            random_state=random_state,
        )


@dataclass
class DoublyRobust(BaseOffPolicyEstimator):
    """Doubly Robust (DR) Estimator.

    Note
    -------
    Similar to DM, DR first learns a supervised machine learning model, such as ridge regression and gradient boosting,
    to estimate the mean reward function (:math:`q(x,a) = \\mathbb{E}[r|x,a]`).
    It then uses it to estimate the policy value as follows.

    .. math::

        \\hat{V}_{\\mathrm{DR}} (\\pi_e; \\mathcal{D}, \\hat{q})
        := \\mathbb{E}_{\\mathcal{D}}[\\hat{q}(x_t,\\pi_e) +  w(x_t,a_t) (r_t - \\hat{q}(x_t,a_t))],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`.
    :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    :math:`\\hat{q} (x,a)` is an estimated expected reward given :math:`x` and :math:`a`.
    :math:`\\hat{q} (x_t,\\pi):= \\mathbb{E}_{a \\sim \\pi(a|x)}[\\hat{q}(x,a)]` is the expectation of the estimated reward function over :math:`\\pi`.
    When the weight-clipping is applied, a large importance weight is clipped as :math:`\\hat{w}(x,a) := \\min \\{ \\lambda, w(x,a) \\}`
    where :math:`\\lambda (>0)` is a hyperparameter that decides a maximum allowed importance weight.

    To estimate the mean reward function, please use `obp.ope.regression_model.RegressionModel`,
    which supports several fitting methods specific to OPE such as *more robust doubly robust*.

    DR mimics IPW to use a weighted version of rewards, but DR also uses the estimated mean reward
    function (the regression model) as a control variate to decrease the variance.
    It preserves the consistency of IPW if either the importance weight or
    the mean reward estimator is accurate (a property called double robustness).
    Moreover, DR is semiparametric efficient when the mean reward estimator is correctly specified.

    Parameters
    ----------
    lambda_: float, default=np.inf
        A maximum possible value of the importance weight.
        When a positive finite value is given, importance weights larger than `lambda_` will be clipped.
        DoublyRobust with a finite positive `lambda_` corresponds to Doubly Robust with Pessimistic Shrinkage of Su et al.(2020) or CAB-DR of Su et al.(2019).

    estimator_name: str, default='dr'.
        Name of the estimator.

    use_estimated_pscore: bool, default=False.
        If True, estimated_pscore is used to estimate policy values.
        If False, pscore is used to estimate policy values.

    References
    ----------
    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    Mehrdad Farajtabar, Yinlam Chow, and Mohammad Ghavamzadeh.
    "More Robust Doubly Robust Off-policy Evaluation.", 2018.

    Yi Su, Lequn Wang, Michele Santacatterina, and Thorsten Joachims.
    "CAB: Continuous Adaptive Blending Estimator for Policy Evaluation and Learning", 2019.

    Yi Su, Maria Dimakopoulou, Akshay Krishnamurthy, and Miroslav Dudík.
    "Doubly robust off-policy evaluation with shrinkage.", 2020.

    """

    lambda_: float = np.inf
    estimator_name: str = "dr"
    use_estimated_pscore: bool = False

    def __post_init__(self) -> None:
        """Initialize Class."""
        check_scalar(
            self.lambda_,
            name="lambda_",
            target_type=(int, float),
            min_val=0.0,
        )
        if self.lambda_ != self.lambda_:
            raise ValueError("lambda_ must not be nan")
        if not isinstance(self.use_estimated_pscore, bool):
            raise TypeError(
                f"`use_estimated_pscore` must be a bool, but {type(self.use_estimated_pscore)} is given"
            )

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like or Tensor, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model or Tensor: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by the DR estimator.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        n_rounds = action.shape[0]
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        # weight clipping
        if isinstance(iw, np.ndarray):
            iw = np.minimum(iw, self.lambda_)
        q_hat_at_position = estimated_rewards_by_reg_model[
            np.arange(n_rounds), :, position
        ]
        q_hat_factual = estimated_rewards_by_reg_model[
            np.arange(n_rounds), action, position
        ]
        pi_e_at_position = action_dist[np.arange(n_rounds), :, position]

        if isinstance(reward, np.ndarray):
            estimated_rewards = np.average(
                q_hat_at_position,
                weights=pi_e_at_position,
                axis=1,
            )
        else:
            raise ValueError("reward must be 1D array")

        estimated_rewards += iw * (reward - q_hat_factual)
        return estimated_rewards

    def estimate_policy_value(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        estimated_pscore: Optional[np.ndarray] = None,
    ) -> float:
        """Estimate the policy value of evaluation policy.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,), can be None
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.
            If self.use_estimated_pscore is False, pscore must not be None.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        estimated_pscore: array-like, shape (n_rounds,), default=None
            Estimated value of action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\hat{\\pi}_b(a_t|x_t)`.
            If self.use_estimated_pscore is True, estimated_pscore must not be None.

        Returns
        ----------
        V_hat: float
            Policy value estimated by the DR estimator.

        """
        check_array(
            array=estimated_rewards_by_reg_model,
            name="estimated_rewards_by_reg_model",
            expected_dim=3,
        )
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        if self.use_estimated_pscore:
            check_array(array=estimated_pscore, name="estimated_pscore", expected_dim=1)
            pscore_ = estimated_pscore
        else:
            check_array(array=pscore, name="pscore", expected_dim=1)
            pscore_ = pscore
        check_ope_inputs(
            action_dist=action_dist,
            position=position,
            action=action,
            reward=reward,
            pscore=pscore_,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        return self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            pscore=pscore_,
            action_dist=action_dist,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
        ).mean()

    def estimate_interval(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        estimated_pscore: Optional[np.ndarray] = None,
        alpha: float = 0.05,
        n_bootstrap_samples: int = 10000,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,), can be None
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.
            If self.use_estimated_pscore is False, pscore must not be None.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        estimated_pscore: array-like, shape (n_rounds,), default=None
            Estimated value of action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\hat{\\pi}_b(a_t|x_t)`.
            If self.use_estimated_pscore is True, estimated_pscore must not be None.

        alpha: float, default=0.05
            Significance level.

        n_bootstrap_samples: int, default=10000
            Number of resampling performed in the bootstrap procedure.

        random_state: int, default=None
            Controls the random seed in bootstrap sampling.

        Returns
        ----------
        estimated_confidence_interval: Dict[str, float]
            Dictionary storing the estimated mean and upper-lower confidence bounds.

        """
        check_array(
            array=estimated_rewards_by_reg_model,
            name="estimated_rewards_by_reg_model",
            expected_dim=3,
        )
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        if self.use_estimated_pscore:
            check_array(array=estimated_pscore, name="estimated_pscore", expected_dim=1)
            pscore_ = estimated_pscore
        else:
            check_array(array=pscore, name="pscore", expected_dim=1)
            pscore_ = pscore
        check_ope_inputs(
            action_dist=action_dist,
            position=position,
            action=action,
            reward=reward,
            pscore=pscore_,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        estimated_round_rewards = self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            pscore=pscore_,
            action_dist=action_dist,
            estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
        )
        return estimate_confidence_interval_by_bootstrap(
            samples=estimated_round_rewards,
            alpha=alpha,
            n_bootstrap_samples=n_bootstrap_samples,
            random_state=random_state,
        )

    def _estimate_mse_score(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        use_bias_upper_bound: bool = True,
        delta: float = 0.05,
    ) -> float:
        """Estimate the MSE score of a given clipping hyperparameter to conduct hyperparameter tuning.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        use_bias_upper_bound: bool, default=True
            Whether to use bias upper bound in hyperparameter tuning.
            If False, direct bias estimator is used to estimate the MSE.

        delta: float, default=0.05
            A confidence delta to construct a high probability upper bound based on the Bernstein’s inequality.

        Returns
        ----------
        estimated_mse_score: float
            Estimated MSE score of a given clipping hyperparameter `lambda_`.
            MSE score is the sum of (high probability) upper bound of bias and the sample variance.
            This is estimated using the automatic hyperparameter tuning procedure
            based on Section 5 of Su et al.(2020).

        """
        n_rounds = reward.shape[0]
        # estimate the sample variance of DR with clipping
        sample_variance = np.var(
            self._estimate_round_rewards(
                reward=reward,
                action=action,
                pscore=pscore,
                action_dist=action_dist,
                estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
                position=position,
            )
        )
        sample_variance /= n_rounds

        # estimate the (high probability) upper bound of the bias of DR with clipping
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        if use_bias_upper_bound:
            bias_term = estimate_high_probability_upper_bound_bias(
                reward=reward,
                iw=iw,
                iw_hat=np.minimum(iw, self.lambda_),
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
                delta=delta,
            )
        else:
            bias_term = estimate_bias_in_ope(
                reward=reward,
                iw=iw,
                iw_hat=np.minimum(iw, self.lambda_),
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
            )
        estimated_mse_score = sample_variance + (bias_term ** 2)

        return estimated_mse_score


@dataclass
class SelfNormalizedDoublyRobust(DoublyRobust):
    """Self-Normalized Doubly Robust (SNDR) Estimator.

    Note
    -------
    Self-Normalized Doubly Robust estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{SNDR}} (\\pi_e; \\mathcal{D}, \\hat{q}) :=
        \\mathbb{E}_{\\mathcal{D}} \\left[\\hat{q}(x_t,\\pi_e) +  \\frac{w(x_t,a_t) (r_t - \\hat{q}(x_t,a_t))}{\\mathbb{E}_{\\mathcal{D}}[ w(x_t,a_t) ]} \\right],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    :math:`\\hat{q} (x,a)` is an estimated expected reward given :math:`x` and :math:`a`.
    :math:`\\hat{q} (x_t,\\pi):= \\mathbb{E}_{a \\sim \\pi(a|x)}[\\hat{q}(x,a)]` is the expectation of the estimated reward function over :math:`\\pi`.
    To estimate the mean reward function, please use `obp.ope.regression_model.RegressionModel`.

    Similar to Self-Normalized Inverse Probability Weighting, SNDR estimator applies the self-normalized importance weighting technique to
    increase the stability of the original Doubly Robust estimator.

    Parameters
    ----------
    estimator_name: str, default='sndr'.
        Name of the estimator.

    References
    ----------
    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    Nathan Kallus and Masatoshi Uehara.
    "Intrinsically Efficient, Stable, and Bounded Off-Policy Evaluation for Reinforcement Learning.", 2019.

    """

    estimator_name: str = "sndr"

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like or Tensor, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by the SNDR estimator.

        """
        n_rounds = action.shape[0]
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        q_hat_at_position = estimated_rewards_by_reg_model[
            np.arange(n_rounds), :, position
        ]
        pi_e_at_position = action_dist[np.arange(n_rounds), :, position]

        if isinstance(reward, np.ndarray):
            estimated_rewards = np.average(
                q_hat_at_position,
                weights=pi_e_at_position,
                axis=1,
            )
        else:
            raise ValueError("reward must be 1D array")

        q_hat_factual = estimated_rewards_by_reg_model[
            np.arange(n_rounds), action, position
        ]
        estimated_rewards += iw * (reward - q_hat_factual) / iw.mean()
        return estimated_rewards


@dataclass
class SwitchDoublyRobust(DoublyRobust):
    """Switch Doubly Robust (Switch-DR) Estimator.

    Note
    -------
    Switch-DR aims to reduce the variance of the DR estimator by using direct method when the importance weight is large.
    This estimator estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{SwitchDR}} (\\pi_e; \\mathcal{D}, \\hat{q}, \\lambda)
        := \\mathbb{E}_{\\mathcal{D}} [\\hat{q}(x_t,\\pi_e) +  w(x_t,a_t) (r_t - \\hat{q}(x_t,a_t)) \\mathbb{I} \\{ w(x_t,a_t) \\le \\lambda \\}],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    :math:`\\lambda (\\ge 0)` is a switching hyperparameter, which decides the threshold for the importance weight.
    :math:`\\hat{q} (x,a)` is an estimated expected reward given :math:`x` and :math:`a`.
    :math:`\\hat{q} (x_t,\\pi):= \\mathbb{E}_{a \\sim \\pi(a|x)}[\\hat{q}(x,a)]` is the expectation of the estimated reward function over :math:`\\pi`.
    To estimate the mean reward function, please use `obp.ope.regression_model.RegressionModel`.

    Parameters
    ----------
    lambda_: float, default=np.inf
        Switching hyperparameter. When importance weight is larger than this parameter, DM is applied, otherwise DR is used.
        This hyperparameter should be larger than or equal to 0., otherwise it is meaningless.

    estimator_name: str, default='switch-dr'.
        Name of the estimator.

    References
    ----------
    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    Yu-Xiang Wang, Alekh Agarwal, and Miroslav Dudík.
    "Optimal and Adaptive Off-policy Evaluation in Contextual Bandits", 2016.

    Yi Su, Maria Dimakopoulou, Akshay Krishnamurthy, and Miroslav Dudik.
    "Doubly Robust Off-Policy Evaluation with Shrinkage.", 2020.

    """

    lambda_: float = np.inf
    estimator_name: str = "switch-dr"

    def __post_init__(self) -> None:
        """Initialize Class."""
        check_scalar(
            self.lambda_,
            name="lambda_",
            target_type=(int, float),
            min_val=0.0,
        )
        if self.lambda_ != self.lambda_:
            raise ValueError("lambda_ must not be nan")

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like, shape (n_rounds,)
            Rewards of each round estimated by the Switch-DR estimator.

        """
        n_rounds = action.shape[0]
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        switch_indicator = np.array(iw <= self.lambda_, dtype=int)
        q_hat_at_position = estimated_rewards_by_reg_model[
            np.arange(n_rounds), :, position
        ]
        q_hat_factual = estimated_rewards_by_reg_model[
            np.arange(n_rounds), action, position
        ]
        pi_e_at_position = action_dist[np.arange(n_rounds), :, position]
        estimated_rewards = np.average(
            q_hat_at_position,
            weights=pi_e_at_position,
            axis=1,
        )
        estimated_rewards += switch_indicator * iw * (reward - q_hat_factual)
        return estimated_rewards

    def _estimate_mse_score(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        use_bias_upper_bound: bool = False,
        delta: float = 0.05,
    ) -> float:
        """Estimate the MSE score of a given switching hyperparameter to conduct hyperparameter tuning.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        use_bias_upper_bound: bool, default=True
            Whether to use bias upper bound in hyperparameter tuning.
            If False, direct bias estimator is used to estimate the MSE.

        delta: float, default=0.05
            A confidence delta to construct a high probability upper bound based on the Bernstein’s inequality.

        Returns
        ----------
        estimated_mse_score: float
            Estimated MSE score of a given switching hyperparameter `lambda_`.
            MSE score is the sum of (high probability) upper bound of bias and the sample variance.
            This is estimated using the automatic hyperparameter tuning procedure
            based on Section 5 of Su et al.(2020).

        """
        n_rounds = reward.shape[0]
        # estimate the sample variance of Switch-DR (Eq.(8) of Wang et al.(2017))
        sample_variance = np.var(
            self._estimate_round_rewards(
                reward=reward,
                action=action,
                pscore=pscore,
                action_dist=action_dist,
                estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
                position=position,
            )
        )
        sample_variance /= n_rounds

        # estimate the (high probability) upper bound of the bias of Switch-DR
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        if use_bias_upper_bound:
            bias_term = estimate_high_probability_upper_bound_bias(
                reward=reward,
                iw=iw,
                iw_hat=iw * np.array(iw <= self.lambda_, dtype=int),
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
                delta=delta,
            )
        else:
            bias_term = estimate_bias_in_ope(
                reward=reward,
                iw=iw,
                iw_hat=iw * np.array(iw <= self.lambda_, dtype=int),
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
            )
        estimated_mse_score = sample_variance + (bias_term ** 2)

        return estimated_mse_score


@dataclass
class DoublyRobustWithShrinkage(DoublyRobust):
    """Doubly Robust with optimistic shrinkage (DRos) Estimator.

    Note
    ------
    DR with (optimistic) shrinkage replaces the importance weight in the original DR estimator with a new weight mapping
    found by directly optimizing sharp bounds on the resulting MSE.

    .. math::

        \\hat{V}_{\\mathrm{DRos}} (\\pi_e; \\mathcal{D}, \\hat{q}, \\lambda)
        := \\mathbb{E}_{\\mathcal{D}} [\\hat{q}(x_t,\\pi_e) +  w_o(x_t,a_t;\\lambda) (r_t - \\hat{q}(x_t,a_t))],

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`.
    :math:`w(x,a):=\\pi_e (a|x)/\\pi_b (a|x)` is the importance weight given :math:`x` and :math:`a`.
    :math:`\\hat{q} (x_t,\\pi):= \\mathbb{E}_{a \\sim \\pi(a|x)}[\\hat{q}(x,a)]` is the expectation of the estimated reward function over :math:`\\pi`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    :math:`\\hat{q} (x,a)` is an estimated expected reward given :math:`x` and :math:`a`.
    To estimate the mean reward function, please use `obp.ope.regression_model.RegressionModel`.

    :math:`w_{o} (x_t,a_t;\\lambda)` is a new weight by the shrinkage technique which is defined as

    .. math::

        w_{o} (x_t,a_t;\\lambda) := \\frac{\\lambda}{w^2(x_t,a_t) + \\lambda} w(x_t,a_t).

    When :math:`\\lambda=0`, we have :math:`w_{o} (x,a;\\lambda)=0` corresponding to the DM estimator.
    In contrast, as :math:`\\lambda \\rightarrow \\infty`, :math:`w_{o} (x,a;\\lambda)` increases and in the limit becomes equal to the original importance weight, corresponding to the standard DR estimator.

    Parameters
    ----------
    lambda_: float
        Shrinkage hyperparameter.
        This hyperparameter should be larger than or equal to 0., otherwise it is meaningless.

    estimator_name: str, default='dr-os'.
        Name of the estimator.

    References
    ----------
    Miroslav Dudík, Dumitru Erhan, John Langford, and Lihong Li.
    "Doubly Robust Policy Evaluation and Optimization.", 2014.

    Yi Su, Maria Dimakopoulou, Akshay Krishnamurthy, and Miroslav Dudik.
    "Doubly Robust Off-Policy Evaluation with Shrinkage.", 2020.

    """

    lambda_: float = 0.0
    estimator_name: str = "dr-os"

    def __post_init__(self) -> None:
        """Initialize Class."""
        check_scalar(
            self.lambda_,
            name="lambda_",
            target_type=(int, float),
            min_val=0.0,
        )
        if self.lambda_ != self.lambda_:
            raise ValueError("lambda_ must not be nan")

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like or Tensor, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by the DRos estimator.

        """
        n_rounds = action.shape[0]
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        if self.lambda_ < np.inf:
            iw_hat = (self.lambda_ * iw) / (iw ** 2 + self.lambda_)
        else:
            iw_hat = iw
        q_hat_at_position = estimated_rewards_by_reg_model[
            np.arange(n_rounds), :, position
        ]
        q_hat_factual = estimated_rewards_by_reg_model[
            np.arange(n_rounds), action, position
        ]
        pi_e_at_position = action_dist[np.arange(n_rounds), :, position]

        if isinstance(reward, np.ndarray):
            estimated_rewards = np.average(
                q_hat_at_position,
                weights=pi_e_at_position,
                axis=1,
            )
        else:
            raise ValueError("reward must be 1D array")

        estimated_rewards += iw_hat * (reward - q_hat_factual)
        return estimated_rewards

    def _estimate_mse_score(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        pscore: np.ndarray,
        action_dist: np.ndarray,
        estimated_rewards_by_reg_model: np.ndarray,
        position: Optional[np.ndarray] = None,
        use_bias_upper_bound: bool = False,
        delta: float = 0.05,
    ) -> float:
        """Estimate the MSE score of a given shrinkage hyperparameter to conduct hyperparameter tuning.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        pscore: array-like, shape (n_rounds,)
            Action choice probabilities of behavior policy (propensity scores), i.e., :math:`\\pi_b(a_t|x_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        estimated_rewards_by_reg_model: array-like, shape (n_rounds, n_actions, len_list)
            Expected rewards given context, action, and position estimated by regression model, i.e., :math:`\\hat{q}(x_t,a_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.

        use_bias_upper_bound: bool, default=True
            Whether to use bias upper bound in hyperparameter tuning.
            If False, direct bias estimator is used to estimate the MSE.

        delta: float, default=0.05
            A confidence delta to construct a high probability upper bound based on the Bernstein’s inequality.

        Returns
        ----------
        estimated_mse_score: float
            Estimated MSE score of a given shrinkage hyperparameter `lambda_`.
            MSE score is the sum of (high probability) upper bound of bias and the sample variance.
            This is estimated using the automatic hyperparameter tuning procedure
            based on Section 5 of Su et al.(2020).

        """
        n_rounds = reward.shape[0]
        # estimate the sample variance of DRos
        sample_variance = np.var(
            self._estimate_round_rewards(
                reward=reward,
                action=action,
                pscore=pscore,
                action_dist=action_dist,
                estimated_rewards_by_reg_model=estimated_rewards_by_reg_model,
                position=position,
            )
        )
        sample_variance /= n_rounds

        # estimate the (high probability) upper bound of the bias of DRos
        iw = action_dist[np.arange(n_rounds), action, position] / pscore
        if self.lambda_ < np.inf:
            iw_hat = (self.lambda_ * iw) / (iw ** 2 + self.lambda_)
        else:
            iw_hat = iw
        if use_bias_upper_bound:
            bias_term = estimate_high_probability_upper_bound_bias(
                reward=reward,
                iw=iw,
                iw_hat=iw_hat,
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
                delta=0.05,
            )
        else:
            bias_term = estimate_bias_in_ope(
                reward=reward,
                iw=iw,
                iw_hat=iw_hat,
                q_hat=estimated_rewards_by_reg_model[
                    np.arange(n_rounds), action, position
                ],
            )
        estimated_mse_score = sample_variance + (bias_term ** 2)

        return estimated_mse_score


@dataclass
class BalancedInverseProbabilityWeighting(BaseOffPolicyEstimator):
    """Balanced Inverse Probability Weighting (IPW) Estimator.

    Note (WIP)
    -------
    Balanced Inverse Probability Weighting (IPW) estimates the policy value of evaluation policy :math:`\\pi_e` by

    .. math::

        \\hat{V}_{\\mathrm{B-IPW}} (\\pi_e; \\mathcal{D}) := \\frac{\\mathbb{E}_{\\mathcal{D}} [\\pi_e (a_t|x_t) \\hat{\\rho}(x_t,a_t) r_t]}{\\mathbb{E}_{\\mathcal{D}} [\\pi_e (a_t|x_t) \\hat{\\rho}(x_t,a_t)},

    where :math:`\\mathcal{D}=\\{(x_t,a_t,r_t)\\}_{t=1}^{T}` is logged bandit feedback data with :math:`T` rounds collected by
    a behavior policy :math:`\\pi_b`. :math:`\\hat{\\rho}(x,a):=\\Pr[C=1|x,a] / \\Pr[C=0|x,a]`, where :math:`\\Pr[C=1|x,a]` is the probability that the action :math:`a` is sampled by evaluation policy given :math:`x`.
    :math:`\\mathbb{E}_{\\mathcal{D}}[\\cdot]` is the empirical average over :math:`T` observations in :math:`\\mathcal{D}`.
    When the weight-clipping is applied, a large importance sampling ratio is clipped as :math:`\\hat{\\rho_c}(x,a) := \\min \\{ \\lambda, \\hat{\\rho}(x,a) \\}`
    where :math:`\\lambda (>0)` is a hyperparameter that decides a maximum allowed importance weight.

    Balanced IPW re-weights the rewards by the ratio of the evaluation policy and behavior policy (importance sampling ratio).
    Balanced IPW can be used even when the behavior policy (or the propensity score of the behavior policy) is not known or the behavior policy is deterministic.
    When the evaluation policy is stochastic, it is not well known whether the balanced IPW performs well.

    Parameters
    ------------
    lambda_: float, default=np.inf
        A maximum possible value of the importance weight.
        When a positive finite value is given, importance weights larger than `lambda_` will be clipped.

    estimator_name: str, default='b-ipw'.
        Name of the estimator.

    References
    ------------
    Arjun Sondhi, David Arbour, and Drew Dimmery
    "Balanced Off-Policy Evaluation in General Action Spaces.", 2020.

    """

    lambda_: float = np.inf
    estimator_name: str = "b-ipw"

    def __post_init__(self) -> None:
        """Initialize Class."""
        check_scalar(
            self.lambda_,
            name="lambda_",
            target_type=(int, float),
            min_val=0.0,
        )
        if self.lambda_ != self.lambda_:
            raise ValueError("lambda_ must not be nan")

    def _estimate_round_rewards(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        importance_sampling_ratio: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate round-wise (or sample-wise) rewards.

        Parameters
        ----------
        reward: array-like or Tensor, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like or Tensor, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        importance_sampling_ratio: array-like or Tensor, shape (n_rounds,)
            Ratio of probability that the action is sampled by evaluation policy divided by probability that the action is sampled by behavior policy,
            i.e., :math:`\\hat{\\rho}(x_t, a_t)`.

        action_dist: array-like or Tensor, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like or Tensor, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        estimated_rewards: array-like or Tensor, shape (n_rounds,)
            Rewards of each round estimated by Balanced IPW.

        """
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        iw = (
            action_dist[np.arange(action.shape[0]), action, position]
            * importance_sampling_ratio
        )
        # weight clipping
        if isinstance(iw, np.ndarray):
            iw = np.minimum(iw, self.lambda_)
        return reward * iw / iw.mean()

    def estimate_policy_value(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        action_dist: np.ndarray,
        context: np.ndarray,
        importance_sampling_ratio: np.ndarray,
        position: Optional[np.ndarray] = None,
        action_context: Optional[np.ndarray] = None,
        **kwargs,
    ) -> np.ndarray:
        """Estimate the policy value of evaluation policy.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        importance_sampling_ratio: array-like or Tensor, shape (n_rounds,)
            Ratio of probability that the action is sampled by evaluation policy divided by probability that the action is sampled by behavior policy,
            i.e., :math:`\\hat{\\rho}(x_t, a_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        Returns
        ----------
        V_hat: float
            Estimated policy value (performance) of a given evaluation policy.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        check_array(
            array=importance_sampling_ratio,
            name="importance_sampling_ratio",
            expected_dim=1,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)
        return self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            importance_sampling_ratio=importance_sampling_ratio,
            action_dist=action_dist,
        ).mean()

    def estimate_interval(
        self,
        reward: np.ndarray,
        action: np.ndarray,
        importance_sampling_ratio: np.ndarray,
        action_dist: np.ndarray,
        position: Optional[np.ndarray] = None,
        alpha: float = 0.05,
        n_bootstrap_samples: int = 10000,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, float]:
        """Estimate confidence interval of policy value by nonparametric bootstrap procedure.

        Parameters
        ----------
        reward: array-like, shape (n_rounds,)
            Reward observed in each round of the logged bandit feedback, i.e., :math:`r_t`.

        action: array-like, shape (n_rounds,)
            Action sampled by behavior policy in each round of the logged bandit feedback, i.e., :math:`a_t`.

        importance_sampling_ratio: array-like or Tensor, shape (n_rounds,)
            Ratio of probability that the action is sampled by evaluation policy divided by probability that the action is sampled by behavior policy,
            i.e., :math:`\\hat{\\rho}(x_t, a_t)`.

        action_dist: array-like, shape (n_rounds, n_actions, len_list)
            Action choice probabilities of evaluation policy (can be deterministic), i.e., :math:`\\pi_e(a_t|x_t)`.

        position: array-like, shape (n_rounds,), default=None
            Position of recommendation interface where action was presented in each round of the given logged bandit data.
            When None is given, the effect of position on the reward will be ignored.
            (If only one action is chosen and there is no posion, then you can just ignore this argument.)

        alpha: float, default=0.05
            Significance level.

        n_bootstrap_samples: int, default=10000
            Number of resampling performed in the bootstrap procedure.

        random_state: int, default=None
            Controls the random seed in bootstrap sampling.

        Returns
        ----------
        estimated_confidence_interval: Dict[str, float]
            Dictionary storing the estimated mean and upper-lower confidence bounds.

        """
        check_array(array=reward, name="reward", expected_dim=1)
        check_array(array=action, name="action", expected_dim=1)
        check_array(
            array=importance_sampling_ratio,
            name="importance_sampling_ratio",
            expected_dim=1,
        )
        check_ope_inputs(
            action_dist=action_dist,
            position=position,
            action=action,
            reward=reward,
            importance_sampling_ratio=importance_sampling_ratio,
        )
        if position is None:
            position = np.zeros(action_dist.shape[0], dtype=int)

        estimated_round_rewards = self._estimate_round_rewards(
            reward=reward,
            action=action,
            position=position,
            importance_sampling_ratio=importance_sampling_ratio,
            action_dist=action_dist,
        )
        return estimate_confidence_interval_by_bootstrap(
            samples=estimated_round_rewards,
            alpha=alpha,
            n_bootstrap_samples=n_bootstrap_samples,
            random_state=random_state,
        )
