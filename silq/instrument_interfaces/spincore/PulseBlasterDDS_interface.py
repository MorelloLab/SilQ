import numpy as np
import logging

from silq.instrument_interfaces \
    import InstrumentInterface, Channel
from silq.pulses import SinePulse, PulseImplementation, TriggerPulse


logger = logging.getLogger(__name__)

RESET_PHASE_FALSE = 0
RESET_PHASE_TRUE = 1

RESET_PHASE = RESET_PHASE_FALSE

DEFAULT_CH_INSTR = (0, 0, 0, 0, 0)
DEFAULT_INSTR = DEFAULT_CH_INSTR + DEFAULT_CH_INSTR

class PulseBlasterDDSInterface(InstrumentInterface):

    def __init__(self, instrument_name, **kwargs):
        super().__init__(instrument_name, **kwargs)


        self._output_channels = {
            # Measured output ranged from -3V to 3 V @ 50 ohm Load.
            f'ch{k}': Channel(instrument_name=self.instrument_name(),
                              name=f'ch{k}',
                              id=k-1, # id is 0-based due to spinapi DLL
                              #output=(-3.0, 3.0)
                              output=True)
            for k in [1, 2]}

        self._channels = {
            **self._output_channels,
            'software_trig_in': Channel(instrument_name=self.instrument_name(),
                                        name='software_trig_in',
                                        input_trigger=True),
            'trig_in': Channel(instrument_name=self.instrument_name(),
                               name='trig_in',
                               input_trigger=True,
                               invert=True)} # Going from high to low triggers

        self.pulse_implementations = [
            SinePulseImplementation(
                pulse_requirements=[('amplitude', {'min': 0, 'max': 1/0.6})])]

    def get_additional_pulses(self, **kwargs):
        # Request one trigger at the start if not primary
        # TODO test if this works
        if not self.is_primary():
            return [TriggerPulse(t_start=0,
                                 connection_requirements={
                                     'input_instrument': self.instrument_name(),
                                     'trigger': True})]
        else:
            return []

    def setup(self, final_instruction='loop', is_primary=True, **kwargs):
        #Initial pulseblaster commands
        self.instrument.setup()

        # Set channel registers for frequencies, phases, and amplitudes
        for channel in self.instrument.output_channels:
            frequencies = []
            phases = []
            amplitudes = []

            pulses = self.pulse_sequence.get_pulses(
                output_channel=channel.short_name)
            for pulse in pulses:
                if isinstance(pulse, SinePulse):
                    frequencies.append(pulse.frequency) # in MHz
                    phases.append(pulse.phase)
                    amplitudes.append(pulse.amplitude)
                else:
                    raise NotImplementedError(f'{pulse} not implemented')

            frequencies = list(set(frequencies))
            phases = list(set(phases))
            amplitudes = list(set(amplitudes))

            channel.frequencies(frequencies)
            channel.phases(phases)
            channel.amplitudes(amplitudes)

            self.instrument.set_frequencies(frequencies=frequencies,
                                            channel=channel.idx)
            self.instrument.set_phases(phases=phases, channel=channel.idx)
            self.instrument.set_amplitudes(amplitudes=amplitudes,
                                           channel=channel.idx)

        ms = 1e6 # points per millisecond

        # Iteratively increase time
        t = 0
        t_stop_max = max(self.pulse_sequence.t_stop_list)
        inst_list = []

        if not is_primary:
            # Wait for trigger
            inst_list.append(DEFAULT_INSTR + (0, 'wait', 0, 100))

        while t < t_stop_max:
            # find time of next event
            t_next = min(t_val for t_val in self.pulse_sequence.t_list
                         if t_val > t)

            # Send continue instruction until next event
            delay_duration = t_next - t
            delay_cycles = round(delay_duration * ms)
            # Either send continue command or long_delay command if the
            # delay duration is too long

            inst = ()
            # for each channel, search for active pulses and implement them
            for ch in sorted(self._output_channels.keys()):
                instrument_channel = self.instrument.output_channels[ch]

                pulse = self.pulse_sequence.get_pulse(enabled=True,
                                                      t=t,
                                                      output_channel=ch)
                if pulse is not None:
                    pulse_implementation = pulse.implementation.implement(
                        frequencies=instrument_channel.frequencies(),
                        phases=instrument_channel.phases(),
                        amplitudes=instrument_channel.amplitudes())
                    inst = inst + pulse_implementation
                else:
                    inst = inst + DEFAULT_CH_INSTR

            if delay_cycles < 1e9:
                inst = inst + (0, 'continue', 0, delay_cycles)
            else:
                # TODO: check to see if a call to long_delay sets the channel registers
                duration = round(delay_cycles - 100)
                divisor = int(np.ceil(duration / 1e9))
                delay = int(duration / divisor)
                inst = inst + (0, 'long_delay', divisor, delay)

            inst_list.append(inst)

            t = t_next

        if is_primary:
            # Insert delay until end of pulse sequence
            # NOTE: This will disable all output channels and use default registers
            delay_duration = max(self.pulse_sequence.duration - t, 0)
            if delay_duration:
                delay_cycles = round(delay_duration * ms)
                if delay_cycles < 1e9:
                    inst = DEFAULT_INSTR + (0, 'continue', 0, delay_cycles)
                else:
                    # TODO: check to see if a call to long_delay sets the channel registers
                    duration = round(delay_cycles - 100)
                    divisor = int(np.ceil(duration / 1e9))
                    delay = int(duration / divisor)
                    inst = DEFAULT_INSTR + (0, 'long_delay', divisor, delay)

                inst_list.append(inst)

        # Loop back to beginning (wait if not primary)
        inst = DEFAULT_INSTR + (0, 'branch', 0, 100)
        inst_list.append(inst)

        # Note that this command does not actually send anything to the DDS,
        # this is done when DDS.start is called
        self.instrument.instruction_sequence(inst_list)

    def start(self):
        self.instrument.start()

    def stop(self):
        self.instrument.stop()


class SinePulseImplementation(PulseImplementation):
    pulse_class = SinePulse

    def implement(self, frequencies, phases, amplitudes):
        frequency_idx = frequencies.index(self.pulse.frequency) # MHz
        phase_idx = phases.index(self.pulse.phase)
        amplitude_idx = amplitudes.index(self.pulse.amplitude)

        inst_slice = (
            frequency_idx,
            phase_idx,
            amplitude_idx,
            1, # Enable channel
            RESET_PHASE)
        return inst_slice