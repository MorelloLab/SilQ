from .interface import InstrumentInterface, Channel
from silq.tools import get_instrument_class


def get_instrument_interface(instrument):
    from .lecroy.ArbStudio1104_interface import ArbStudio1104Interface
    from .chip_interface import ChipInterface
    from .spincore.PulseBlasterESRPRO_interface import \
        PulseBlasterESRPROInterface
    from .AlazarTech.ATS_interface import ATSInterface

    instrument_interfaces = {
        'ArbStudio1104': ArbStudio1104Interface,
        'MockArbStudio': ArbStudio1104Interface,
        'PulseBlasterESRPRO': PulseBlasterESRPROInterface,
        'MockPulseBlaster': PulseBlasterESRPROInterface,
        'Chip': ChipInterface,
        'ATS9440': ATSInterface,
        'MockATS': ATSInterface
    }

    instrument_class = get_instrument_class(instrument)
    instrument_interface_class = instrument_interfaces[instrument_class]

    server_name = getattr(instrument, '_server_name', None)

    instrument_interface = instrument_interface_class(
        instrument_name=instrument.name,
        server_name=server_name)
    return instrument_interface