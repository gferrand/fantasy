"""Direct regression coverage for shared deterministic intelligence adapters."""

from unittest.mock import patch

from fantasy_advisor.intelligence_capabilities import get_watchlist_stats
from fantasy_advisor.watchlist import WatchlistPlayer


def test_watchlist_adapter_preserves_the_existing_stats_contract():
    watched = [WatchlistPlayer("p", "Player", "IPS", ("M",), "")]
    sentinel = object()
    with patch("fantasy_advisor.intelligence_capabilities.load_current_watchlist_stats", return_value=sentinel) as load:
        assert get_watchlist_stats(watched) is sentinel
    load.assert_called_once_with(watched, include_trends=True, include_previous_season=True)
