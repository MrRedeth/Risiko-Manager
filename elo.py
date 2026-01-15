import math
from typing import List, Dict, Tuple

class Elo:
    """
    Handles ELO rating calculations for Multiplayer Risk matches.
    Implementation: Winner takes all.
    The winner is treated as having played a 1v1 match against every other opponent.
    There are no comparisons between the losers.
    """

    @staticmethod
    def expected_score(rating_a: float, rating_b: float) -> float:
        """
        Calculate expected score for player A against player B.
        Formula: 1 / (1 + 10 ^ ((Rb - Ra) / 400))
        """
        return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))

    @staticmethod
    def calculate_deltas(winner_rating: float, loser_ratings: List[float], k_factor: float) -> Tuple[float, List[float]]:
        """
        Calculates rating changes.
        
        Args:
            winner_rating: Current rating of the winner.
            loser_ratings: List of current ratings of all other players.
            k_factor: The K-factor to use for this match.
            
        Returns:
            Tuple containing:
            - Winner's rating delta (float)
            - List of losers' rating deltas (List[float]), in same order as input.
        """
        winner_delta = 0.0
        loser_deltas = []

        # Calculate Winner vs Each Loser
        for l_rating in loser_ratings:
            # Expected score for Winner vs this Loser
            exp_win = Elo.expected_score(winner_rating, l_rating)
            
            # Winner actually won (score 1)
            # Delta = K * (Actual - Expected)
            single_match_win_delta = k_factor * (1.0 - exp_win)
            winner_delta += single_match_win_delta

            # Reverse for Loser
            # Expected score for Loser vs Winner
            exp_loss = Elo.expected_score(l_rating, winner_rating)
            
            # Loser actually lost (score 0)
            # Delta = K * (0 - Expected)
            single_match_loss_delta = k_factor * (0.0 - exp_loss)
            loser_deltas.append(single_match_loss_delta)
            
        return winner_delta, loser_deltas
