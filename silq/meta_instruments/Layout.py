from functools import partial
from silq.pulses import TriggerPulse
from silq.instrument_interfaces import InstrumentInterface, Channel

from qcodes import Instrument
from qcodes.instrument.parameter import ManualParameter
from qcodes.utils import validators as vals

class Layout(Instrument):
    shared_kwargs=['instrument_interfaces']
    def __init__(self, name, instrument_interfaces, **kwargs):
        super().__init__(name, **kwargs)

        # Add interfaces for each instrument to self.instruments
        self._interfaces = {interface.instrument_name(): interface
                             for interface in instrument_interfaces}

        self.connections = []

        self.add_parameter('trigger_instrument',
                           parameter_class=ManualParameter,
                           initial_value=None,
                           vals=vals.Enum(*self._interfaces.keys()))

        self.add_parameter('acquisition_instrument',
                           parameter_class=ManualParameter,
                           initial_value=None,
                           vals=vals.Enum(*self._interfaces.keys()))
        self.add_parameter('instruments',
                           get_cmd=lambda: list(self._interfaces.keys()))

    # def close(self):
    #     for interface in self._interfaces.values():
    #         print('closing {}'.format(interface))
    #         interface.close()
    #     super().close()

    def add_connection(self, output, input, **kwargs):
        connection = SingleConnection(output, input, **kwargs)
        self.connections += [connection]
        return connection

    def combine_connections(self, *connections, **kwargs):
        connection = CombinedConnection(connections=connections, **kwargs)
        self.connections += [connection]
        return connection

    def get_connections(self, output_interface=None, output_instrument=None, output_channel=None,
                        input_interface=None, input_instrument=None, input_channel=None,
                        trigger=None):
        """
        Returns all connections that satisfy given kwargs
        Args:
            output_interface: Connections must have output_interface
            output_instrument: Connections must have output_instrument name
            output_channel: Connections must have output_channel
            input_interface: Connections must have input_interface
            input_instrument: Connections must have input_instrument name
            input_channel: Connections must have input_channel

        Returns:
            Connections that satisfy kwarg constraints
        """
        filtered_connections = self.connections
        if output_interface is not None:
            output_instrument = output_interface.instrument_name()
        if output_instrument is not None:
            filtered_connections = filter(
                lambda c: c.output['instrument'] == output_instrument,
                filtered_connections
            )

        if output_channel is not None:
            if isinstance(output_instrument, Channel):
                output_channel = output_channel.name
            filtered_connections = filter(
                lambda c: c.output['channel'] == output_channel,
                filtered_connections
            )

        if input_interface is not None:
            input_instrument = input_interface.instrument_name()
        if input_instrument is not None:
            filtered_connections = filter(
                lambda c: c.input['instrument'] == input_instrument,
                filtered_connections
            )
        if input_channel is not None:
            if isinstance(input_instrument, Channel):
                input_channel = input_channel.name
            filtered_connections = filter(
                lambda c: c.input['channel'] == input_channel,
                filtered_connections
            )
        if trigger is not None:
            filtered_connections = filter(
                lambda c: c.trigger==trigger,
                filtered_connections
            )


        return list(filtered_connections)

    def _get_pulse_interface(self, pulse):
        """
        Retrieves the instrument interface to output pulse
        Args:
            pulse: Pulse for which to find the default instrument interface

        Returns:
            Instrument interface for pulse
        """
        interfaces = [interface for interface in
                       self._interfaces.values() if
                       interface.get_pulse_implementation(pulse)]
        if not interfaces:
            raise Exception('No instruments have an implementation for pulses '
                            '{}'.format(pulse))
        elif len(interfaces) > 1:
            raise Exception('More than one instrument have an implementation '
                            'for pulses {}. Functionality to choose instrument '
                            'not yet implemented'.format(pulse))
        else:
            return interfaces[0]

    def get_pulse_instrument(self, pulse):
        """
        Retrieves the instrument name to output pulse
        Args:
            pulse: Pulse for which to find the default instrument name

        Returns:
            Instrument name for pulse
        """
        interface = self._get_pulse_interface(pulse)
        return interface.instrument_name()

    def get_pulse_connection(self, pulse, interface=None, instrument=None,
                             **kwargs):
        """
        Obtain default connection for a given pulse. If no instrument or
        instrument_name is given, the instrument is determined from
        self.get_pulse_instrument.
        Args:
            pulse: Pulse for which to find default connection
            interface (optional): Output instrument interface of pulse
            instrument (optional): Output instrument name of pulse
            **kwargs: Additional kwargs to specify connection

        Returns:
            Connection object for pulse
        """
        if interface is not None:
            connections = self.get_connections(
                output_interface=interface, **kwargs)
        elif instrument is not None:
            connections = self.get_connections(
                output_instrument=instrument, **kwargs)
        else:
            interface = self._get_pulse_interface(pulse)
            connections = self.get_connections(
                output_interface=interface, **kwargs)


        default_connections = [connection for connection in connections
                               if connection.default]
        if not default_connections:
            raise Exception('Instrument {} has connections {}, but none are '
                            'set as default'.format(interface, connections))
        elif len(default_connections) > 1:
            raise Exception('Instrument {} has connections {}, and more than'
                            'one are set as default'.format(interface,
                                                            connections))
        else:
            return default_connections[0]

    def target_pulse_sequence(self, pulse_sequence):
        # Clear pulses sequences of all instruments
        for interface in self._interfaces.values():
            interface.clear_pulses()

        # Add pulses in pulse_sequence to pulse_sequences of instruments
        for pulse in pulse_sequence:
            # Get default output instrument
            interface = self._get_pulse_interface(pulse)
            connection = self.get_pulse_connection(pulse, interface=interface)

            targeted_pulse = pulse.copy()
            targeted_pulse.connection = connection
            interface.add_pulse(targeted_pulse)

            # If instrument is not the main triggering instrument, add triggers
            # to each of the triggering instruments until you reach the main
            # triggering instrument.
            # TODO this should only be done in some cases, for instance if an
            # Arbstudio is the input instrument and is in stepped mode
            while interface.instrument_name() != self.trigger_instrument():
                print(interface.instrument_name(), self.trigger_instrument())
                trigger_connections = self.get_connections(
                    input_interface=interface, trigger=True)
                assert len(trigger_connections) == 1, \
                    "Did not find exactly one triggering connection: {}. " \
                    "All connections: {}".format(
                        trigger_connections, self.connections
                    )
                connection = trigger_connections[0]
                print('found trigger connection')
                # Replace instrument by its triggering instrument
                interface = self._interfaces[connection.output['instrument']]
                interface.add_pulse(
                    TriggerPulse(t_start=pulse.t_start, connection=connection,
                                 t_stop=pulse.t_start))

        # Setup each of the instruments using its pulse_sequence
        for interface in self._interfaces.values():
            interface.setup()

        # TODO setup acquisition instrument


class Connection:
    def __init__(self, default=False):
        self.input = {}
        self.output = {}

        # TODO make default dependent on implementation
        self.default = default

class SingleConnection(Connection):
    def __init__(self, output, input,
                 trigger=False, acquire=False, **kwargs):
        """
        Class representing a connection between instrument channels.

        Args:
            output: Specification of output channel.
                Can be:
                    str "{instrument_name}.{output_channel_name}"
                    tuple ({instrument_name}, {output_channel_name})
            input_channel:
            trigger (bool): Sets the output channel to trigger the input
                instrument
            acquire (bool): Sets if this connection is used for acquisition
            default (bool): Sets if this connection is the default for pulses
        """
        # TODO add optionality of having multiple channels connected.
        # TODO Add mirroring of other channel.
        super().__init__(**kwargs)

        if type(output) is str:
            output_instrument, output_channel = output.split('.')
        elif type(output) is tuple:
            output_instrument, output_channel = output
        self.output['instrument'] = output_instrument
        self.output['channel'] = output_channel

        if type(input) is str:
            input_instrument, input_channel = input.split('.')
        elif type(input) is tuple:
            input_instrument, input_channel = input
        self.input['instrument'] = input_instrument
        self.input['channel'] = input_channel

        self.trigger = trigger
        # TODO add this connection to input_instrument.trigger

        self.acquire = acquire

    def __repr__(self):
        output_str = "Connection{{{}.{}->{}.{}}}(".format(
            self.output['instrument'], self.output['channel'],
            self.input['instrument'], self.input['channel'])
        if self.trigger:
            output_str += ', trigger'
        if self.default:
            output_str += ', default'
        if self.acquire:
            output_str += ', acquire'
        output_str += ')'
        return output_str


class CombinedConnection(Connection):
    def __init__(self, connections, scaling_factors=None, **kwargs):
        super().__init__(**kwargs)
        self.connections = connections
        self.output['instruments'] = list(set([connection.output['instrument']
                                          for connection in connections]))
        if len(self.output['instruments']) == 1:
            self.output['instrument'] = self.output['instruments'][0]
        else:
            raise Exception('Connections with multiple output instruments not'
                            'yet supported')
        self.output['channels'] = list(set([connection.output['channel']
                                       for connection in connections]))
        self.input['instruments'] = list(set([connection.input['instrument']
                                         for connection in connections]))
        self.input['channels'] = list(set([connection.input['channel']
                                      for connection in connections]))

        if scaling_factors is None:
            scaling_factors = {connection.input['channel']: 1
                               for connection in connections}
        elif type(scaling_factors) is list:
            # Convert scaling factors to dictionary with channel keys
            scaling_factors = {connection.input['channel']: scaling_factor
                               for (connection, scaling_factor)
                               in zip(connections, scaling_factors)}
        self.scaling_factors = scaling_factors
