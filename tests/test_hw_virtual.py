"""The desktop / MPF Monitor overlay (config.yaml + hw_virtual.yaml): smart_virtual with a full trough at
power-on, trough ejects that reach the shooter lane, and trough switches that shift like the real trough."""
from tests.tron_test import TronTestCase

TROUGH = ("s_trough_1_r", "s_trough_2", "s_trough_3", "s_trough_4_l")


class TestHwVirtual(TronTestCase):

    def get_config_file(self):
        return "../../tests/machine_virtual.yaml"     # relative to game/config

    def get_platform(self):
        return False                                  # the overlay's own platform

    def trough(self):
        return [self.machine.switches[name].state for name in TROUGH]

    def test_machine(self):
        self.assertEqual("pro", self.machine.variables.get_machine_var("machine_variant"))
        self.assertEqual("4", self.machine.switches["s_tron_t"].hw_switch.number)      # T-R-O-N standups, reversed
        self.assertEqual("3", self.machine.coils["c_disc_direction_relay"].hw_driver.number)
        self.assertEqual("virtual", self.machine.coils["c_drop_target_bank"].config["platform"])

    def test_trough_eject_and_shift(self):
        self.assertEqual("<Platform.SmartVirtual>", repr(self.machine.default_platform))
        self.advance_time_and_run(1)
        self.assertEqual([1, 1, 1, 1], self.trough())                 # starts full
        self.assertEqual(4, self.machine.ball_devices["bd_trough"].balls)
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertModeRunning("game")
        self.assertSwitchState("s_shooter_lane", 1)
        self.assertEqual([1, 1, 1, 0], self.trough())                 # the balls rolled down
        self.assertEqual(3, self.machine.ball_devices["bd_trough"].balls)


class TestHwVirtualLe(TestHwVirtual):
    """hw_virtual_le.yaml: the LE's numbers; hw_virtual.yaml (above) is the Pro's."""

    def get_config_file(self):
        return "../../tests/machine_virtual_le.yaml"

    def test_machine(self):
        self.assertEqual("le", self.machine.variables.get_machine_var("machine_variant"))
        self.assertEqual("1", self.machine.switches["s_tron_t"].hw_switch.number)
        self.assertEqual("3", self.machine.coils["c_drop_target_bank"].hw_driver.number)


class TestFreePlayOverlay(TronTestCase):
    """run.py's desktop default: free play, so START begins a game without a coin."""

    FREE_PLAY = False                                 # the overlay's own default, not the test override

    def get_config_file(self):
        return "../../tests/machine_free_play.yaml"

    def get_platform(self):
        return False

    def test_start_without_coin(self):
        self.assertTrue(self.tron.credit_model.free_play())
        self.assertEqual(0, self.tron.credit_model.credits)
        self.advance_time_and_run(1)
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertModeRunning("game")


class TestCoinWithoutFreePlay(TronTestCase):
    """hw_virtual alone keeps the factory setting: START needs a credit, the coin switch gives it."""

    FREE_PLAY = False

    def get_config_file(self):
        return "../../tests/machine_virtual.yaml"

    def get_platform(self):
        return False

    def test_coin_then_start(self):
        self.assertFalse(self.tron.credit_model.free_play())
        self.advance_time_and_run(1)
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertModeNotRunning("game")
        for _ in range(3):                            # USA 1 credit / 3 coin units on the right slot
            self.hit_and_release_switch("s_coin")
            self.advance_time_and_run(1)
        self.assertGreaterEqual(self.tron.credit_model.credits, 1)
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertModeRunning("game")
