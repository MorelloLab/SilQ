from typing import List, Dict, Any, Union, Tuple, Sequence
import numpy as np
from copy import copy, deepcopy
copy_alias = copy  # Alias for functions that have copy as a kwarg
from blinker import Signal
from matplotlib import pyplot as plt

from qcodes.instrument.parameter_node import parameter
from qcodes import ParameterNode, Parameter
from qcodes.utils import validators as vals

__all__ = ['PulseRequirement', 'PulseSequence', 'PulseImplementation']


class PulseRequirement():
    """`Pulse` attribute requirement for a `PulseImplementation`

    This class is used in Interfaces when registering a `PulseImplementation`,
    to impose additional constraints for implementing the pulse.

    The class is never directly instantiated, but is instead created from a dict
    passed to the ``pulse_requirements`` kwarg of a `PulseImplementation`.

    Example:
        For an AWG can apply sine pulses, but only up to its Nyquist limit
        ``max_frequency``, the following implementation is used:

        >>> SinePulseImplementation(
                pulse_requirements=[('frequency', {'max': max_frequency})])

    Args:
        property: Pulse attribute for which to place a constraint.
        requirement: Requirement that a property must satisfy.

            * If a dict, allowed keys are ``min`` and ``max``, the value being
              the minimum/maximum value.
            * If a list, the property must be an element in the list.
    """
    def __init__(self,
                 property: str,
                 requirement: Union[list, Dict[str, Any]]):
        self.property = property

        self.verify_requirement(requirement)
        self.requirement = requirement

    def __repr__(self):
        return f'{self.property} - {self.requirement}'

    def verify_requirement(self, requirement):
        """Verifies that the requirement is valid.

        A valid requirement is either a list, or a dict with keys ``min`` and/or
        ``max``.

        Raises:
            AssertionError: Requirement is not valid.
        """
        if type(requirement) is list:
            assert requirement, "Requirement must not be an empty list"
        elif type(requirement) is dict:
            assert ('min' in requirement or 'max' in requirement), \
                "Dictionary condition must have either a 'min' or a 'max'"

    def satisfies(self, pulse) -> bool:
        """Checks if a given pulses satisfies this PulseRequirement.

        Args:
            pulse: Pulse to be verified.

        Returns:
            True if pulse satisfies PulseRequirement.

        Raises:
            Exception: Pulse requirement cannot be interpreted.

        """
        property_value = getattr(pulse, self.property)

        # Test for condition
        if type(self.requirement) is dict:
            # requirement contains min and/or max
            if 'min' in self.requirement and \
                            property_value < self.requirement['min']:
                return False
            elif 'max' in self.requirement and \
                            property_value > self.requirement['max']:
                return False
            else:
                return True
        elif type(self.requirement) is list:
            if property_value not in self.requirement:
                return False
            else:
                return True
        else:
            raise Exception(
                "Cannot interpret pulses requirement: {self.requirement}")


class PulseSequence(ParameterNode):
    """`Pulse` container that can be targeted in the `Layout`.

    It can be used to store untargeted or targeted pulses.

    If multiple pulses with the same name are added, `Pulse`.id is set for the
    pulses sharing the same name, starting with 0 for the first pulse.

    **Retrieving pulses**
        To retrieve a pulse with name 'read':

        >>> pulse_sequence['read']
        >>> pulse_sequence.get_pulse(name='read')

        Both methods work, but the latter is more versatile, as it also allows
        filtering of pulses by discriminants other than name.

        If there are multiple pulses with the same name, the methods above will
        raise an error because there is no unique pulse with name ``read``.
        Instead, the `Pulse`.id must also be passed to discriminate the pulses:

        >>> pulse_sequence['read[0]']
        >>> pulse_sequence.get_pulse(name='read', id=0)

        Both methods return the first pulse added whose name is 'read'.

    **Iterating over pulses**
        Pulses in a pulse sequence can be iterated over via:

        >>> for pulse in pulse_sequence:
        >>>     # perform actions

        This will return the pulses sorted by `Pulse`.t_start.
        Pulses for which `Pulse`.enabled is False are ignored.

    **Checking if pulse sequence contains a pulse**
        Pulse sequences can be treated similar to a list, and so checking if a
        pulse exists in a list is done as such:

        >>> pulse in pulse_sequence

        Note that this does not compare object equality, but only checks if all
        attributes match.

    **Checking if a pulse sequence contains pulses**
        Checking if a pulse sequence contains pulses is similar to a list:

        >>> if pulse_sequence:
        >>>     # pulse_sequence contains pulses

    **Targeting a pulse sequence in the `Layout`**
        A pulse sequence can be targeted in the layout, which will distribute
        the pulses among it's `InstrumentInterface` such that the pulse sequence
        is executed. Targeting of a pulse sequence is straightforward:

        >>> layout.pulse_sequence = pulse_sequence

        After this, the instruments can be configured via `Layout.setup`.


    Parameters:
        pulses (List[Pulse]): `Pulse` list to place in PulseSequence.
            Pulses can also be added later using `PulseSequence.add`.
        allow_untargeted_pulses (bool): Allow untargeted pulses (without
            corresponding `Pulse`.implementation) to be added to PulseSequence.
            `InstrumentInterface`.pulse_sequence should have this unchecked.
        allow_targeted_pulses (bool): Allow targeted pulses (with corresponding
            `Pulse`.implementation) to be added to PulseSequence.
            `InstrumentInterface`.pulse_sequence should have this checked.
        allow_pulse_overlap (bool): Allow pulses to overlap in time. If False,
            an error will be raised if a pulse is added that overlaps in time.
            If pulse has a `Pulse`.connection, an error is only raised if
            connections match as well.
        duration (float): Total duration of pulse sequence. Equal to
            `Pulse`.t_stop of last pulse, unless explicitly set.
            Can be reset to t_stop of last pulse by setting to None, and will
            automatically be reset every time a pulse is added/removed.
        final_delay (Union[float, None]): Optional final delay at the end of
            the pulse sequence. The interface of the primary instrument should
            incorporate any final delay. The default is .5 ms
        enabled_pulses (List[Pulse]): `Pulse` list with `Pulse`.enabled True.
            Updated when a pulse is added or `Pulse`.enabled is changed.
        disabled_pulses (List[Pulse]): Pulse list with `Pulse`.enabled False.
            Updated when a pulse is added or `Pulse`.enabled is changed.
        t_start_list (List[float]): `Pulse`.t_start list for all enabled pulses.
            Can contain duplicates if pulses share the same `Pulse`.t_start.
        t_stop_list (List[float]): `Pulse`.t_stop list for all enabled pulses.
            Can contain duplicates if pulses share the same `Pulse`.t_stop.
        t_list (List[float]): Combined list of `Pulse`.t_start and
            `Pulse`.t_stop for all enabled pulses. Does not contain duplicates.

    Notes:
        * If pulses are added without `Pulse`.t_start defined, the pulse is
          assumed to start after the last pulse finishes, and a connection is
          made with the attribute `t_stop` of the last pulse, such that if the
          last pulse t_stop changes, t_start is changed accordingly.
        * All pulses in the pulse sequence are listened to via `Pulse`.signal.
          Any time an attribute of a pulse changes, a signal will be emitted,
          which can then be interpreted by the pulse sequence.
    """

    connection_conditions = None
    pulse_conditions = None
    default_final_delay = .5e-3
    def __init__(self,
                 pulses: list = None,
                 allow_untargeted_pulses: bool = True,
                 allow_targeted_pulses: bool = True,
                 allow_pulse_overlap: bool = True,
                 final_delay: float = None):
        super().__init__(use_as_attributes=True,
                         log_changes=False,
                         simplify_snapshot=True)

        # For PulseSequence.satisfies_conditions, we need to separate conditions
        # into those relating to pulses and to connections. We perform an import
        # here because it otherwise otherwise leads to circular imports
        if self.connection_conditions is None or self.pulse_conditions is None:
            from silq.meta_instruments.layout import connection_conditions
            from silq.pulses import pulse_conditions
            PulseSequence.connection_conditions = connection_conditions
            PulseSequence.pulse_conditions = pulse_conditions

        self.allow_untargeted_pulses = Parameter(initial_value=allow_untargeted_pulses,
                                                 set_cmd=None,
                                                 vals=vals.Bool())
        self.allow_targeted_pulses = Parameter(initial_value=allow_targeted_pulses,
                                               set_cmd=None,
                                               vals=vals.Bool())
        self.allow_pulse_overlap = Parameter(initial_value=allow_pulse_overlap,
                                             set_cmd=None,
                                             vals=vals.Bool())

        self.duration = Parameter(unit='s', set_cmd=None)
        self.final_delay = Parameter(unit='s', set_cmd=None, vals=vals.Numbers())
        if final_delay is not None:
            self.final_delay = final_delay
        else:
            self.final_delay = self.default_final_delay

        self.t_list = Parameter(initial_value=[0])
        self.t_start_list = Parameter(initial_value=[])
        self.t_stop_list = Parameter()

        self.enabled_pulses = Parameter(initial_value=[], set_cmd=None,
                                        vals=vals.Lists())
        self.disabled_pulses = Parameter(initial_value=[], set_cmd=None,
                                         vals=vals.Lists())
        self.pulses = Parameter(initial_value=[], vals=vals.Lists(),
                                set_cmd=None)

        self.duration = None  # Reset duration to t_stop of last pulse
        # Perform a separate set to ensure set method is called
        self.pulses = pulses or []

    @parameter
    def pulses_set_parser(self, parameter, pulses):
        # We modify the set_parser instead of set, since we don't want to set
        # pulses to the original pulses, but to the added (copied) pulses
        self.clear()
        added_pulses = self.quick_add(*pulses)
        self.finish_quick_add()
        return added_pulses

    @parameter
    def duration_get(self, parameter):
        if parameter._duration is not None:
            return parameter._duration
        else:
            if self.enabled_pulses:
                duration = max([0] + self.t_stop_list)
            else:
                duration = 0

            return np.round(duration, 11)

    @parameter
    def duration_set_parser(self, parameter, duration):
        if duration is None:
            parameter._duration = None
            return max([0] + self.t_stop_list)
        else:
            parameter._duration = np.round(duration, 11)
            return parameter._duration

    @parameter
    def t_start_list_get(self, parameter):
        # Use get_latest for speedup
        return sorted({pulse['t_start'].get_raw()
                       for pulse in self.enabled_pulses})

    @parameter
    def t_stop_list_get(self, parameter):
        # Use get_latest for speedup
        return sorted({pulse['t_stop'].get_raw()
                       for pulse in self.enabled_pulses})

    @parameter
    def t_list_get(self, parameter):
        # Note: Set does not work accurately when dealing with floating point numbers to remove duplicates
        # t_list = self.t_start_list + self.t_stop_list + [self.duration]
        # return sorted(list(np.unique(np.round(t_list, decimals=8)))) # Accurate to 10 ns
        return sorted(set(self.t_start_list + self.t_stop_list + [self.duration]))

    def __getitem__(self, index):
        if isinstance(index, int):
            return self.enabled_pulses[index]
        elif isinstance(index, str):
            pulses = [p for p in self.pulses
                      if p.satisfies_conditions(name=index)]
            if pulses:
                if len(pulses) != 1:
                    raise KeyError(f"Could not find unique pulse with name "
                                   f"{index}, pulses found:\n{pulses}")
                return pulses[0]
            else:
                return super().__getitem__(index)

    def __len__(self):
        return len(self.enabled_pulses)

    def __bool__(self):
        return len(self.enabled_pulses) > 0

    def __contains__(self, item):
        if isinstance(item, str):
            return any(pulse for pulse in self.pulses
                      if item in [pulse.name, pulse.full_name])
        else:
            return item in self.pulses

    def __repr__(self):
        output = str(self) + '\n'
        for pulse in self.enabled_pulses:
            pulse_repr = repr(pulse)
            # Add a tab to each line
            pulse_repr = '\t'.join(pulse_repr.splitlines(True))
            output += '\t' + pulse_repr + '\n'

        if self.disabled_pulses:
            output += '\t\n\tDisabled pulses:\n'
            for pulse in self.disabled_pulses:
                pulse_repr = repr(pulse)
                # Add a tab to each line
                pulse_repr = '\t'.join(pulse_repr.splitlines(True))
                output += '\t' + pulse_repr + '\n'
        return output

    def __str__(self):
        return f'PulseSequence with {len(self.pulses)} pulses, ' \
               f'duration: {self.duration}'

    def __eq__(self, other):
        """Overwrite comparison with other (self == other).

        We want the comparison to return True if other is a pulse with the
        same attributes. This can be complicated since pulses can also be
        targeted, resulting in a pulse implementation. We therefore have to
        use a separate comparison when either is a Pulse implementation
        """
        if not isinstance(other, PulseSequence):
            return False

        for parameter_name, parameter in self.parameters.items():
            if not parameter_name in other.parameters:
                return False
            elif parameter() != getattr(other, parameter_name):
                return False
        # All parameters match
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __copy__(self, *args):
        # Temporarily remove pulses from parameter so they won't be deepcopied
        pulses = self.parameters['pulses']._latest
        enabled_pulses = self.parameters['enabled_pulses']._latest
        disabled_pulses = self.parameters['disabled_pulses']._latest
        try:
            self.parameters['pulses']._latest = {'value': [], 'raw_value': []}
            self.parameters['enabled_pulses']._latest = {'value': [], 'raw_value': []}
            self.parameters['disabled_pulses']._latest = {'value': [], 'raw_value': []}

            self_copy = super().__copy__()
        finally:
            # Restore pulses
            self.parameters['pulses']._latest = pulses
            self.parameters['enabled_pulses']._latest = enabled_pulses
            self.parameters['disabled_pulses']._latest = disabled_pulses

        # Add pulses (which will create copies)
        self_copy.pulses = self.pulses

        # If duration is fixed (i.e. pulse_sequence.duration=val), ensure this
        # is also copied
        self_copy['duration']._duration = self['duration']._duration
        return self_copy

    def _ipython_key_completions_(self):
        """Tab completion for IPython, i.e. pulse_sequence["p..."] """
        return [pulse.full_name for pulse in self.pulses]

    def snapshot_base(self, update: bool=False,
                      params_to_skip_update: Sequence[str]=[]):
        """
        State of the pulse sequence as a JSON-compatible dict.

        Args:
            update (bool): If True, update the state by querying the
                instrument. If False, just use the latest values in memory.
            params_to_skip_update: List of parameter names that will be skipped
                in update even if update is True. This is useful if you have
                parameters that are slow to update but can be updated in a
                different way (as in the qdac)

        Returns:
            dict: base snapshot
        """
        # Ensure the following paraeters have the latest values
        for parameter_name in ['duration', 't_list', 't_start_list', 't_stop_list']:
            self.parameters[parameter_name].get()

        snap = super().snapshot_base(update=update,
                                     params_to_skip_update=params_to_skip_update)
        snap.pop('enabled_pulses', None)

        snap['pulses'] = [pulse.snapshot(update=update,
                                         params_to_skip_update=params_to_skip_update)
                          for pulse in self.pulses]
        return snap

    def add(self, *pulses,
            reset_duration: bool = True):
        """Adds pulse(s) to the PulseSequence.

        Args:
            *pulses (Pulse): Pulses to add
            reset_duration: Reset duration of pulse sequence to t_stop of final
                pulse

        Returns:
            List[Pulse]: Added pulses, which are copies of the original pulses.

        Raises:
            AssertionError: The added pulse overlaps with another pulses and
                `PulseSequence`.allow_pulses_overlap is False
            AssertionError: The added pulse is untargeted and
                `PulseSequence`.allow_untargeted_pulses is False
            AssertionError: The added pulse is targeted and
                `PulseSequence`.allow_targeted_pulses is False
            ValueError: If a pulse has no duration

        Note:
            When a pulse is added, it is first copied, to ensure that the
            original pulse remains unmodified.
            For an speed-optimized version, see `PulseSequence.quick_add`
        """
        pulses_no_duration = [pulse for pulse in pulses if pulse.duration is None]
        if pulses_no_duration:
            raise ValueError(
                'Please specify pulse duration in silq.config.pulses for the '
                'following pulses: ' ', '.join(p.name for p in pulses_no_duration)
            )

        added_pulses = []

        for pulse in pulses:
            # Perform checks to see if pulse can be added
            if (not self.allow_pulse_overlap
                    and pulse.t_start is not None
                    and any(p for p in self.enabled_pulses
                            if self.pulses_overlap(pulse, p))):
                overlapping_pulses = [p for p in self.enabled_pulses
                                      if self.pulses_overlap(pulse, p)]
                raise AssertionError(f'Cannot add pulse {pulse} because it '
                                     f'overlaps with {overlapping_pulses}')
            assert pulse.implementation is not None or self.allow_untargeted_pulses, \
                f'Cannot add untargeted pulse {pulse}'
            assert pulse.implementation is None or self.allow_targeted_pulses, \
                f'Not allowed to add targeted pulse {pulse}'

            # Copy pulse to ensure original pulse is unmodified
            pulse_copy = copy(pulse)
            pulse_copy.id = None  # Remove any pre-existing pulse id

            # Check if pulse with same name exists, if so ensure unique id
            if pulse.name is not None:
                pulses_same_name = self.get_pulses(name=pulse.name)

                if pulses_same_name:
                    if pulses_same_name[0].id is None:
                        pulses_same_name[0].id = 0
                        pulse_copy.id = 1
                    else:
                        max_id = max(p.id for p in pulses_same_name)
                        pulse_copy.id = max_id + 1

            # If pulse does not have t_start defined, it will be attached to
            # the end of the last pulse on the same connection(_label)
            if pulse_copy.t_start is None and self.pulses:
                # Find relevant pulses that share same connection(_label)
                relevant_pulses = self.get_pulses(connection=pulse.connection,
                                                  connection_label=pulse.connection_label)
                if relevant_pulses:
                    last_pulse = max(relevant_pulses,
                                     key=lambda pulse: pulse.parameters['t_stop'].raw_value)
                    last_pulse['t_stop'].connect(pulse_copy['t_start'], update=True)

            if pulse_copy.t_start is None:  # No relevant pulses found
                pulse_copy.t_start = 0

            self.pulses.append(pulse_copy)
            if pulse_copy.enabled:
                self.enabled_pulses.append(pulse_copy)
            else:
                self.disabled_pulses.append(pulse_copy)
            added_pulses.append(pulse_copy)
            # TODO attach pulsesequence to some of the pulse attributes
            pulse_copy['enabled'].connect(self._update_enabled_disabled_pulses,
                                          update=False)

        self.sort()

        if reset_duration:  # Reset duration to t_stop of last pulse
            self.duration = None

        return added_pulses

    def quick_add(self, *pulses,
                  copy: bool = True,
                  connect: bool = True,
                  reset_duration: bool = True):
        """"Quickly add pulses to a sequence skipping steps and checks.

        This method is used in the during the `Layout` targeting of a pulse
        sequence, and should generally only be used if speed is a crucial factor.

        Note:
            When using this method, make sure to finish adding pulses with
            `PulseSequence.finish_quick_add`.

        The following steps are skipped and are performed in
        `PulseSequence.finish_quick_add`:

        - Assigning a unique pulse id if multiple pulses share the same name
        - Sorting pulses
        - Ensuring no pulses overlapped

        Args:
            *pulses: List of pulses to be added. Note that these won't be copied
                if ``copy`` is False, and so the t_start may be set
            copy: Whether to copy the pulse before applying operations
            reset_duration: Reset duration of pulse sequence to t_stop of final
                pulse

        Returns:
            Added pulses. If copy is False, the original pulses are returned.

        Note:
            If copy is False, the id of original pulses may be set when calling
            `PulseSequence.quick_add`.

        """
        pulses_no_duration = [pulse for pulse in pulses if pulse.duration is None]
        if pulses_no_duration:
            raise SyntaxError('Please specify pulse duration in silq.config.pulses'
                              ' for the following pulses: ' +
                              ', '.join(str(p.name) for p in pulses_no_duration))

        added_pulses = []
        for pulse in pulses:
            assert pulse.implementation is not None or self.allow_untargeted_pulses, \
                f'Cannot add untargeted pulse {pulse}'
            assert pulse.implementation is None or self.allow_targeted_pulses, \
                f'Not allowed to add targeted pulse {pulse}'

            if copy:
                pulse = copy_alias(pulse)

            # TODO set t_start if not set
            # If pulse does not have t_start defined, it will be attached to
            # the end of the last pulse on the same connection(_label)
            if pulse.t_start is None and self.pulses:
                # Find relevant pulses that share same connection(_label)
                relevant_pulses = self.get_pulses(connection=pulse.connection,
                                                  connection_label=pulse.connection_label)
                if relevant_pulses:
                    last_pulse = max(relevant_pulses,
                                     key=lambda pulse: pulse.parameters['t_stop'].raw_value)
                    pulse.t_start = last_pulse.t_stop
                    if connect:
                        last_pulse['t_stop'].connect(pulse['t_start'], update=False)
            if pulse.t_start is None:  # No relevant pulses found
                pulse.t_start = 0

            self.pulses.append(pulse)
            added_pulses.append(pulse)
            if pulse.enabled:
                self.enabled_pulses.append(pulse)
            else:
                self.disabled_pulses.append(pulse)

            # TODO attach pulsesequence to some of the pulse attributes
            if connect:
                pulse['enabled'].connect(self._update_enabled_disabled_pulses,
                                         update=False)

        if reset_duration:  # Reset duration to t_stop of last pulse
            self.duration = None

        return added_pulses

    def finish_quick_add(self):
        """Finish adding pulses via `PulseSequence.quick_add`

        Steps performed:

        - Sorting of pulses
        - Checking that pulses do not overlap
        - Adding unique id's to pulses in case a name is shared by pulses

        """
        try:
            self.sort()

            if not self.allow_pulse_overlap:  # Check pulse overlap
                active_pulses = []
                for pulse in self.enabled_pulses:
                    new_active_pulses = []
                    for active_pulse in active_pulses:
                        if active_pulse.t_stop <= pulse.t_start:
                            continue
                        else:
                            new_active_pulses.append(active_pulse)
                        assert not self.pulses_overlap(pulse, active_pulse), \
                            f"Pulses overlap:\n\t{repr(pulse)}\n\t{repr(active_pulse)}"

                    new_active_pulses.append(pulse)
                    active_pulses = new_active_pulses

            # Ensure all pulses have a unique full_name. This is done by attaching
            # a unique id if multiple pulses share the same name
            unique_names = set(pulse.name for pulse in self.pulses)
            for name in unique_names:
                same_name_pulses = self.get_pulses(name=name)

                # Add ``id`` if several pulses share the same name
                if len(same_name_pulses) > 1:
                    for k, pulse in enumerate(same_name_pulses):
                        pulse.id = k
        except AssertionError:  # Likely error is that pulses overlap
            self.clear()
            raise

    def remove(self, *pulses):
        """Removes `Pulse` or pulses from pulse sequence

        Args:
            pulses: Pulse(s) to remove from PulseSequence

        Raises:
            AssertionError: No unique pulse found
        """
        for pulse in pulses:
            if isinstance(pulse, str):
                pulses_same_name = [p for p in self.pulses if p.full_name==pulse]
            else:
                pulses_same_name = [p for p in self if p == pulse]

            assert len(pulses_same_name) == 1, \
                f'No unique pulse {pulse} found, pulses: {pulses_same_name}'
            pulse_same_name = pulses_same_name[0]

            self.pulses.remove(pulse_same_name)

            # TODO disconnect all pulse attributes
            pulse_same_name['enabled'].disconnect(self._update_enabled_disabled_pulses)

        self._update_enabled_disabled_pulses()
        self.sort()
        self.duration = None  # Reset duration to t_stop of last pulse

    def sort(self):
        """Sort pulses by `Pulse`.t_start"""
        self.pulses.sort(key=lambda p: p.t_start)
        self.enabled_pulses.sort(key=lambda p: p.t_start)

    def clear(self):
        """Clear all pulses from pulse sequence."""
        for pulse in self.pulses:
            # TODO: remove all signal connections
            pulse['enabled'].disconnect(self._update_enabled_disabled_pulses)
        self.pulses.clear()
        self.enabled_pulses.clear()
        self.disabled_pulses.clear()
        self.duration = None  # Reset duration to t_stop of last pulse

    @staticmethod
    def pulses_overlap(pulse1, pulse2) -> bool:
        """Tests if pulse1 and pulse2 overlap in time and connection.

        Args:
            pulse1 (Pulse): First pulse
            pulse2 (Pulse): Second pulse

        Returns:
            True if pulses overlap

        Note:
            If either of the pulses does not have a connection, this is not tested.
        """
        if (pulse1.t_stop <= pulse2.t_start) or (pulse1.t_start >= pulse2.t_stop):
            return False
        elif pulse1.connection is not None:
            if pulse2.connection is not None:
                return pulse1.connection == pulse2.connection
            elif pulse2.connection_label is not None:
                return pulse1.connection.label == pulse2.connection_label
            else:
                return False
        elif pulse1.connection_label is not None:
            # Overlap if the pulse connection labels overlap
            labels = [pulse2.connection_label, getattr(pulse2.connection, 'label', None)]
            return pulse1.connection_label in labels
        else:
            return True

    def get_pulses(self, enabled=True, connection=None, connection_label=None,
                   **conditions):
        """Get list of pulses in pulse sequence satisfying conditions

        Args:
            enabled: Pulse must be enabled
            connection: pulse must have connection
            **conditions: Additional connection and pulse conditions.

        Returns:
            List[Pulse]: Pulses satisfying conditions

        See Also:
            `Pulse.satisfies_conditions`, `Connection.satisfies_conditions`.
        """
        pulses = self.enabled_pulses if enabled else self.pulses
        # Filter pulses by pulse conditions
        pulse_conditions = {k: v for k, v in conditions.items()
                            if k in self.pulse_conditions and v is not None}
        pulses = [pulse for pulse in pulses if pulse.satisfies_conditions(**pulse_conditions)]

        # Filter pulses by pulse connection conditions
        connection_conditions = {k: v for k, v in conditions.items()
                                 if k in self.connection_conditions
                                 and v is not None}

        if connection:
            pulses = [pulse for pulse in pulses if
                      pulse.connection == connection or
                      pulse.connection_label == connection.label != None]
            return pulses  # No further filtering required
        elif connection_label is not None:
            pulses = [pulse for pulse in pulses if
                      getattr(pulse.connection, 'label', None) == connection_label or
                      pulse.connection_label == connection_label]
            return pulses # No further filtering required

        if connection_conditions:
            pulses = [pulse for pulse in pulses if
                      pulse.connection is not None and
                      pulse.connection.satisfies_conditions(**connection_conditions)]

        return pulses

    def get_pulse(self, **conditions):
        """Get unique pulse in pulse sequence satisfying conditions.

        Args:
            **conditions: Connection and pulse conditions.

        Returns:
            Pulse: Unique pulse satisfying conditions

        See Also:
            `Pulse.satisfies_conditions`, `Connection.satisfies_conditions`.

        Raises:
            RuntimeError: No unique pulse satisfying conditions
        """
        pulses = self.get_pulses(**conditions)

        if not pulses:
            return None
        elif len(pulses) == 1:
            return pulses[0]
        else:
            raise RuntimeError(f'Found more than one pulse satisfiying {conditions}')

    def get_connection(self, **conditions):
        """Get unique connections from any pulse satisfying conditions.

        Args:
            **conditions: Connection and pulse conditions.

        Returns:
            Connection: Unique Connection satisfying conditions

        See Also:
            `Pulse.satisfies_conditions`, `Connection.satisfies_conditions`.

        Raises:
            AssertionError: No unique connection satisfying conditions.
        """
        pulses = self.get_pulses(**conditions)
        connections = list({pulse.connection for pulse in pulses})
        assert len(connections) == 1, \
            f"No unique connection found satisfying {conditions}. " \
            f"Connections: {connections}"
        return connections[0]

    def get_transition_voltages(self,
                                pulse = None,
                                connection = None,
                                t: float = None) -> Tuple[float, float]:
        """Finds the voltages at the transition between two pulses.

        Note:
            This method can potentially cause issues, and should be avoided
            until it's better thought through

        Args:
            pulse (Pulse): Pulse starting at transition voltage. If not
                provided, ``connection`` and ``t`` must both be provided.
            connection (Connection): connection along which the voltage
                transition occurs
            t (float): Time at which the voltage transition occurs.

        Returns:
            (Voltage before transition, voltage after transition)
        """
        if pulse is not None:
            post_pulse = pulse
            connection = pulse.connection
            t = pulse.t_start
        elif connection is not None and t is not None:
            post_pulse = self.get_pulse(connection=connection, t_start=t)
        else:
            raise TypeError('Not enough arguments provided')

        # Find pulses thar stop sat t. If t=0, the pulse before this
        #  will be the last pulse in the sequence
        pre_pulse = self.get_pulse(connection=connection,
                                   t_stop=(self.duration if t == 0 else t))
        if pre_pulse is not None:
            pre_voltage = pre_pulse.get_voltage(self.duration if t == 0 else t)
        elif connection.output['channel'].output_TTL:
            # Choose pre voltage as low from TTL
            pre_voltage = connection.output['channel'].output_TTL[0]
        else:
            raise RuntimeError('Could not determine pre voltage for transition')

        post_voltage = post_pulse.get_voltage(t)

        return pre_voltage, post_voltage

    def get_trace_shapes(self,
                         sample_rate: int,
                         samples: int):
        """ Get dictionary of trace shapes for given sample rate and samples

        Args:
            sample_rate: Acquisition sample rate
            samples: acquisition samples.

        Returns:
            Dict[str, tuple]:
            {`Pulse`.full_name: trace_shape}

        Note:
            trace shape depends on `Pulse`.average
        """

        shapes = {}
        for pulse in self:
            if not pulse.acquire:
                continue
            pts = round(pulse.duration * sample_rate)
            if pulse.average == 'point':
                shape = (1,)
            elif pulse.average == 'trace':
                shape = (pts, )
            else:
                shape = (samples, pts)

            shapes[pulse.full_name] = shape

        return shapes

    def plot(self, t_range=None, points=2001, subplots=False, scale_ylim=True,
             figsize=None, legend=True,
             **connection_kwargs):
        pulses = self.get_pulses(**connection_kwargs)

        connection_pulse_list = {}
        for pulse in pulses:
            if pulse.connection_label is not None:
                connection_label = pulse.connection_label
            elif pulse.connection is not None:
                if pulse.connection.label is not None:
                    connection_label = pulse.connection.label
                else:
                    connection_label = pulse.connection.output['str']
            else:
                connection_label = 'Other'

            if connection_label not in connection_pulse_list:
                connection_pulse_list[connection_label] = [pulse]
            else:
                connection_pulse_list[connection_label].append(pulse)

        if subplots:
            figsize = figsize or 10, 1.5 * len(connection_pulse_list)
            fig, axes = plt.subplots(len(connection_pulse_list), 1, sharex=True,
                                     figsize=figsize)
        else:
            figsize = figsize or (10, 4)
            fig, ax = plt.subplots(1, figsize=figsize)
            axes = [ax]

        # Generate t_list
        if t_range is None:
            t_range = (0, self.duration)
        sample_rate = (t_range[1] - t_range[0]) / points
        t_list = np.linspace(*t_range, points)

        voltages = {}
        for k, (connection_label, connection_pulses) in enumerate(
                connection_pulse_list.items()):

            connection_voltages = np.nan * np.ones(len(t_list))
            for pulse in connection_pulses:
                pulse_t_list = np.arange(pulse.t_start, pulse.t_stop,
                                         sample_rate)
                start_idx = np.argmax(t_list >= pulse.t_start)
                # Determine max_pts because sometimes there is a rounding error
                max_pts = len(connection_voltages[
                              start_idx:start_idx + len(pulse_t_list)])
                connection_voltages[
                start_idx:start_idx + len(pulse_t_list)] = pulse.get_voltage(
                    pulse_t_list[:max_pts])
            voltages[connection_label] = connection_voltages

            if subplots:
                ax = axes[k]

            ax.plot(t_list, connection_voltages, label=connection_label)
            if not subplots:
                ax.set_xlabel('Time (s)')
            ax.set_ylabel('Amplitude (V)')
            ax.set_xlim(0, self.duration)

            if legend:
                ax.legend()

        if scale_ylim:
            min_voltage = np.nanmin(np.concatenate(tuple(voltages.values())))
            max_voltage = np.nanmax(np.concatenate(tuple(voltages.values())))
            voltage_difference = max_voltage - min_voltage
            for ax in axes:
                ax.set_ylim(min_voltage - 0.05 * voltage_difference,
                            max_voltage + 0.05 * voltage_difference)

        fig.tight_layout()
        if subplots:
            fig.subplots_adjust(hspace=0)
        return t_list, voltages, fig, axes

    def up_to_date(self) -> bool:
        """Checks if a pulse sequence is up to date or needs to be generated.

        Used by `PulseSequenceGenerator`.

        Returns:
            True by default, can be overridden in subclass.
        """
        return True

    def _update_enabled_disabled_pulses(self, *args):
        self.enabled_pulses = [pulse for pulse in self.pulses if pulse.enabled]
        self.disabled_pulses = [pulse for pulse in self.pulses if not pulse.enabled]


class PulseImplementation:
    """`InstrumentInterface` implementation for a `Pulse`.

    Each `InstrumentInterface` should have corresponding pulse implementations
    for the pulses it can output. These should be subclasses of the
    `PulseImplementation`.

    When a `PulseSequence` is targeted in the Layout, each `Pulse` is directed
    to the relevant `InstrumentInterface`, which will call target the pulse
    using the corresponding PulseImplementation. During `Pulse` targeting,
    a copy of the pulse is made, and the PulseImplementation is added to
    `Pulse`.implementation.

    **Creating a PulseImplementation**
        A PulseImplementation is specific for a certain `Pulse`, which should
        be defined in `PulseImplementation`.pulse_class.

        A `PulseImplementation` subclass may override the following methods:

        * `PulseImplementation.target_pulse`
        * `PulseImplementation.get_additional_pulses`
        * `PulseImplementation.implement`

    Args:
        pulse_requirements: Requirements that pulses must satisfy to allow
            implementation.
    """
    pulse_config = None
    pulse_class = None

    def __init__(self, pulse_requirements=[]):
        self.signal = Signal()
        self._connected_attrs = {}
        self.pulse = None

        # List of conditions that a pulse must satisfy to be targeted
        self.pulse_requirements = [PulseRequirement(property, condition) for
                                 (property, condition) in pulse_requirements]

    def __ne__(self, other):
        return not self.__eq__(other)

    def _matches_attrs(self, other_pulse, exclude_attrs=[]):
        for attr in list(vars(self)):
            if attr in exclude_attrs:
                continue
            elif not hasattr(other_pulse, attr) \
                    or getattr(self, attr) != getattr(other_pulse, attr):
                return False
        else:
            return True

    def add_pulse_requirement(self,
                              property: str,
                              requirement: Union[list, Dict[str, Any]]):
        """Add requirement that any pulse must satisfy to be targeted"""
        self.pulse_requirements += [PulseRequirement(property, requirement)]

    def satisfies_requirements(self,
                               pulse,
                               match_class: bool = True):
        """Checks if a pulse satisfies pulse requirements

        Args:
            pulse (Pulse): Pulse that is checked
            match_class: Pulse class must match
                `PulseImplementation`.pulse_class
        """
        if match_class and not self.pulse_class == pulse.__class__:
            return False
        else:
            return np.all([pulse_requirements.satisfies(pulse)
                           for pulse_requirements in self.pulse_requirements])

    def target_pulse(self,
                     pulse,
                     interface,
                     connections: list,
                     **kwargs):
        """Tailors a PulseImplementation to a specific pulse.

        Targeting happens in three stages:

        1. Both the pulse and pulse implementation are copied.
        2. `PulseImplementation` of the copied pulse is set to the copied
           pulse implementation, and `PulseImplementation`.pulse is set to the
           copied pulse. This way, they can both reference each other.
        3. The targeted pulse is returned

        Args:
            pulse (Pulse): Pulse to be targeted.
            interface (InstrumentInterface) interface to which this
                PulseImplementation belongs.
            connections (List[Connection]): All connections in `Layout`.
            **kwargs: Additional unused kwargs

        Raises:
            TypeError: Pulse class does not match
                `PulseImplementation`.pulse_class

        """
        if not isinstance(pulse, self.pulse_class):
            raise TypeError(f'Pulse {pulse} must be type {self.pulse_class}')

        targeted_pulse = copy(pulse)
        pulse_implementation = deepcopy(self)
        targeted_pulse.implementation = pulse_implementation
        pulse_implementation.pulse = targeted_pulse
        return targeted_pulse

    def get_additional_pulses(self, interface):
        """Provide any additional pulses needed such as triggering pulses

        The additional pulses can be requested should usually have
        `Pulse`.connection_conditions specified to ensure that the pulse is
        sent to the right connection.

        Args:
            interface (InstrumentInterface): Interface to which this
                PulseImplementation belongs

        Returns:
            List[Pulse]: List of additional pulses needed.
        """
        return []

    def implement(self, *args, **kwargs) -> Any:
        """Implements a targeted pulse for an InstrumentInterface.

        This method is called during `InstrumentInterface.setup`.

        Implementation of a targeted pulse is very dependent on the interface.
        For an AWG, this method may return a list of waveform points.
        For a triggering source, this method may return the triggering time.
        In very simple cases, this method may not even be necessary.

        Args:
            *args: Interface-specific args to use
            **kwargs: Interface-specific kwargs to use

        Returns:
            Instrument-specific return values.

        See Also:
            Other interface source codes may serve as a guide for this method.
        """
        raise NotImplementedError('PulseImplementation.implement should be '
                                  'implemented in a subclass')
