import re

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    PathProvider,
    TriggerInfo,
    set_mock_value,
)
from ophyd_async.epics import adaravis


@pytest.fixture
async def test_adaravis(
    RE: RunEngine,
    static_path_provider: PathProvider,
) -> adaravis.AravisDetector:
    async with DeviceCollector(mock=True):
        test_adaravis = adaravis.AravisDetector("ADARAVIS:", static_path_provider)

    return test_adaravis


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_invariant_with_exposure_time(
    exposure_time: float,
    test_adaravis: adaravis.AravisDetector,
):
    assert test_adaravis.controller.get_deadtime(exposure_time) == 1961e-6


async def test_trigger_source_set_to_gpio_line(test_adaravis: adaravis.AravisDetector):
    set_mock_value(test_adaravis.drv.trigger_source, "Freerun")

    async def trigger_and_complete():
        await test_adaravis.controller.arm(num=1, trigger=DetectorTrigger.edge_trigger)
        # Prevent timeouts
        set_mock_value(test_adaravis.drv.acquire, True)

    # Default TriggerSource
    assert (await test_adaravis.drv.trigger_source.get_value()) == "Freerun"
    test_adaravis.set_external_trigger_gpio(1)
    # TriggerSource not changed by setting gpio
    assert (await test_adaravis.drv.trigger_source.get_value()) == "Freerun"

    await trigger_and_complete()

    # TriggerSource changes
    assert (await test_adaravis.drv.trigger_source.get_value()) == "Line1"

    test_adaravis.set_external_trigger_gpio(3)
    # TriggerSource not changed by setting gpio
    await trigger_and_complete()
    assert (await test_adaravis.drv.trigger_source.get_value()) == "Line3"


def test_gpio_pin_limited(test_adaravis: adaravis.AravisDetector):
    assert test_adaravis.get_external_trigger_gpio() == 1
    test_adaravis.set_external_trigger_gpio(2)
    assert test_adaravis.get_external_trigger_gpio() == 2
    with pytest.raises(
        ValueError,
        match=re.escape(
            "AravisDetector only supports the following GPIO indices: "
            "(1, 2, 3, 4) but was asked to use 55"
        ),
    ):
        test_adaravis.set_external_trigger_gpio(55)  # type: ignore


async def test_hints_from_hdf_writer(test_adaravis: adaravis.AravisDetector):
    assert test_adaravis.hints == {"fields": ["test_adaravis"]}


async def test_can_read(test_adaravis: adaravis.AravisDetector):
    # Standard detector can be used as Readable
    assert (await test_adaravis.read()) == {}


async def test_decribe_describes_writer_dataset(test_adaravis: adaravis.AravisDetector):
    set_mock_value(test_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(test_adaravis._writer.hdf.capture, True)

    assert await test_adaravis.describe() == {}
    await test_adaravis.stage()
    assert await test_adaravis.describe() == {
        "test_adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    test_adaravis: adaravis.AravisDetector, static_path_provider: PathProvider
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / "foo.h5"
    set_mock_value(test_adaravis.hdf.full_file_name, str(full_file_name))
    set_mock_value(test_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(test_adaravis._writer.hdf.capture, True)
    await test_adaravis.stage()
    docs = [(name, doc) async for name, doc in test_adaravis.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_adaravis"
    assert stream_resource["uri"] == "file://localhost" + str(full_file_name)
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(test_adaravis: adaravis.AravisDetector):
    set_mock_value(test_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(test_adaravis._writer.hdf.capture, True)
    assert (await test_adaravis.describe_collect()) == {}
    await test_adaravis.stage()
    assert (await test_adaravis.describe_collect()) == {
        "test_adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_unsupported_trigger_excepts(test_adaravis: adaravis.AravisDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"AravisController only supports the following trigger types: .* but",
    ):
        await test_adaravis.prepare(
            TriggerInfo(
                number=1,
                trigger=DetectorTrigger.variable_gate,
                deadtime=1,
                livetime=1,
                frame_timeout=3,
            )
        )
