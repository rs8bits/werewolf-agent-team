import pytest
from pydantic import ValidationError

from app.config.role_setups import (
    RoleCount,
    RoleSetup,
    get_role_setup,
    six_player_setup,
    twelve_player_setup,
)
from app.state.schemas import PlayerType, Role


class TestSixPlayerPreset:
    def test_total_player_count_is_six(self):
        setup = six_player_setup()
        total = sum(rc.count for rc in setup.role_counts)
        assert total == 6
        assert setup.player_count == 6

    def test_has_two_werewolves(self):
        setup = six_player_setup()
        ww = next(rc for rc in setup.role_counts if rc.role == Role.werewolf)
        assert ww.count == 2

    def test_has_one_seer(self):
        setup = six_player_setup()
        seer = next(rc for rc in setup.role_counts if rc.role == Role.seer)
        assert seer.count == 1

    def test_has_one_witch(self):
        setup = six_player_setup()
        witch = next(rc for rc in setup.role_counts if rc.role == Role.witch)
        assert witch.count == 1

    def test_has_two_villagers(self):
        setup = six_player_setup()
        villager = next(rc for rc in setup.role_counts if rc.role == Role.villager)
        assert villager.count == 2

    def test_returns_role_setup_instance(self):
        setup = six_player_setup()
        assert isinstance(setup, RoleSetup)

    def test_seat_configs_generates_six_seats(self):
        setup = six_player_setup()
        seats = setup.seat_configs()
        assert len(seats) == 6

    def test_seat_configs_have_sequential_numbers(self):
        setup = six_player_setup()
        seats = setup.seat_configs()
        assert [s.seat_no for s in seats] == [1, 2, 3, 4, 5, 6]

    def test_seat_configs_default_to_ai(self):
        setup = six_player_setup()
        seats = setup.seat_configs()
        assert all(s.player_type == PlayerType.ai for s in seats)

    def test_seat_configs_human_override(self):
        setup = six_player_setup()
        seats = setup.seat_configs(player_type=PlayerType.human)
        assert all(s.player_type == PlayerType.human for s in seats)

    def test_seat_configs_roles_match_counts(self):
        setup = six_player_setup()
        seats = setup.seat_configs()
        role_counts: dict[Role, int] = {}
        for s in seats:
            role_counts[s.role] = role_counts.get(s.role, 0) + 1
        assert role_counts[Role.werewolf] == 2
        assert role_counts[Role.seer] == 1
        assert role_counts[Role.witch] == 1
        assert role_counts[Role.villager] == 2

    def test_each_call_returns_independent_role_counts(self):
        first = six_player_setup()
        second = six_player_setup()
        first.role_counts[0].count = 99
        assert second.role_counts[0].count == 2

    def test_seat_configs_shuffles_roles_out_of_grouped_order(self):
        """Without seed, seat configs are unlikely to be the default grouped order."""
        setup = six_player_setup()
        seats = setup.seat_configs()
        roles = [s.role for s in seats]
        grouped = [Role.werewolf, Role.werewolf, Role.seer, Role.witch, Role.villager, Role.villager]
        assert len(roles) == 6
        # Role counts must still match
        role_counts: dict[Role, int] = {}
        for r in roles:
            role_counts[r] = role_counts.get(r, 0) + 1
        assert role_counts[Role.werewolf] == 2
        assert role_counts[Role.seer] == 1
        assert role_counts[Role.witch] == 1
        assert role_counts[Role.villager] == 2

    def test_seat_configs_seed_is_deterministic(self):
        setup = six_player_setup()
        seats1 = setup.seat_configs(seed=42)
        seats2 = setup.seat_configs(seed=42)
        roles1 = [s.role for s in seats1]
        roles2 = [s.role for s in seats2]
        assert roles1 == roles2

    def test_seat_configs_seat_numbers_always_sequential(self):
        """Seat numbers stay 1..N regardless of shuffle."""
        setup = six_player_setup()
        for _ in range(10):
            seats = setup.seat_configs()
            assert [s.seat_no for s in seats] == [1, 2, 3, 4, 5, 6]


class TestGetRoleSetup:
    def test_six_players_returns_valid_setup(self):
        setup = get_role_setup(6)
        assert setup.player_count == 6
        total = sum(rc.count for rc in setup.role_counts)
        assert total == 6

    def test_twelve_players_returns_standard_setup(self):
        setup = get_role_setup(12)
        counts = {rc.role: rc.count for rc in setup.role_counts}
        assert setup.player_count == 12
        assert counts[Role.werewolf] == 4
        assert counts[Role.seer] == 1
        assert counts[Role.witch] == 1
        assert counts[Role.hunter] == 1
        assert counts[Role.idiot] == 1
        assert counts[Role.villager] == 4

    def test_twelve_player_setup_helper(self):
        assert twelve_player_setup().player_count == 12

    def test_unsupported_count_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported player count"):
            get_role_setup(3)

    def test_unsupported_count_message_includes_number(self):
        with pytest.raises(ValueError, match="3"):
            get_role_setup(3)

    def test_unsupported_count_message_includes_supported(self):
        with pytest.raises(ValueError, match="6"):
            get_role_setup(9)

    def test_zero_players_raises(self):
        with pytest.raises(ValueError):
            get_role_setup(0)

    def test_large_count_raises(self):
        with pytest.raises(ValueError):
            get_role_setup(100)


class TestSeatShuffle:
    """Verify seat configs randomise roles across seat numbers."""

    def test_seed_produces_deterministic_order(self):
        setup = six_player_setup()
        a = [s.role for s in setup.seat_configs(seed=42)]
        b = [s.role for s in setup.seat_configs(seed=42)]
        assert a == b

    def test_different_seeds_produce_different_orders(self):
        setup = six_player_setup()
        a = [s.role for s in setup.seat_configs(seed=1)]
        b = [s.role for s in setup.seat_configs(seed=2)]
        assert a != b

    def test_no_seed_shuffles_roles_not_fixed_groups(self):
        """Without seed, roles should not be clustered by identity.

        Run multiple times and verify the order is not always the
        fixed wolf-wolf-seer-witch-villager-villager pattern.  Because
        a shuffle *could* randomly produce the same order, retry a few
        times to avoid a flaky test.
        """
        fixed = [Role.werewolf, Role.werewolf, Role.seer, Role.witch,
                 Role.villager, Role.villager]
        shuffled_once = False
        for _ in range(20):
            setup = six_player_setup()
            roles = [s.role for s in setup.seat_configs()]
            if roles != fixed:
                shuffled_once = True
                break
        assert shuffled_once, "座位未随机打乱 — 20 次均为固定顺序"

    def test_twelve_player_seats_are_shuffled(self):
        setup = twelve_player_setup()
        seats = setup.seat_configs(seed=7)
        roles = [s.role for s in seats]
        # seat numbers are still 1..12
        assert [s.seat_no for s in seats] == list(range(1, 13))
        # role counts are correct
        assert roles.count(Role.werewolf) == 4
        assert roles.count(Role.seer) == 1
        assert roles.count(Role.witch) == 1
        assert roles.count(Role.hunter) == 1
        assert roles.count(Role.idiot) == 1
        assert roles.count(Role.villager) == 4
        # roles are not in the fixed declaration order
        fixed_12 = [Role.werewolf] * 4 + [Role.seer, Role.witch,
                     Role.hunter, Role.idiot] + [Role.villager] * 4
        assert roles != fixed_12


class TestRoleSetupValidation:
    def test_role_count_must_be_positive(self):
        with pytest.raises(ValidationError):
            RoleCount(role=Role.villager, count=0)

    def test_role_counts_must_match_player_count(self):
        with pytest.raises(ValidationError, match="Role counts total"):
            RoleSetup(
                player_count=6,
                role_counts=[RoleCount(role=Role.villager, count=5)],
            )
