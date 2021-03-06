from functools import partial

from qcodes import Instrument
from qcodes.instrument.parameter import ManualParameter

class Simrack(Instrument):
    """Combiner of multiple SIM900 modules
    
    Note:
        This module is not finished and has never been tested.
    """
    def __init__(self, name, SIMs, **kwargs):
        super().__init__(name, **kwargs)

        # If SIMs is not a list, we assume it's a single SIM, in which case we convert it to a list
        if not type(SIMs) == list:
            SIMs = [SIMs]

        self.SIMs = SIMs
        # self.total_channels = sum(map(lambda sim: sim.channels, self.SIMs))

        for SIM_idx, SIM in enumerate(self.SIMs):
            #Find alphabetic character for each SIM instrument
            SIM_letter = chr(SIM_idx + ord('A'))
            for channel in range(1, SIM.channels+1):
                self.add_parameter('ch{}{}'.format(SIM_letter, channel),
                                   label='Corrected Gate Channel {}{} (V)'.format(SIM_letter, channel),
                                   get_cmd=partial(self.do_get_voltage,channel=channel, SIM_letter=SIM_letter),
                                   set_cmd=partial(self.do_set_voltage, channel=channel, SIM_letter=SIM_letter))
                self.add_parameter('ch{}{}_divider'.format(SIM_letter, channel),
                                   label='Gate Channel {} divider'.format(channel),
                                   parameter_class=ManualParameter,
                                   initial_value=1
                                   )

    def do_get_voltage(self, SIM_letter, channel):
        SIM_idx = ord(SIM_letter) - ord('A')
        SIM = self.SIMs[SIM_idx]
        raw_voltage = eval('SIM.ch{}()'.format(channel))
        divider = eval('self.ch{}{}_divider()'.format(SIM_letter, channel))
        return raw_voltage/divider

    def do_set_voltage(self, voltage, SIM_letter, channel):
        SIM_idx = ord(SIM_letter) - ord('A')
        SIM = self.SIMs[SIM_idx]
        divider = eval('self.ch{}{}_divider()'.format(SIM_letter, channel))
        eval('SIM.ch{}({})'.format(channel, voltage * divider))