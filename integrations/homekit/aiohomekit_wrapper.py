from contextlib import asynccontextmanager
from pathlib import Path
from aiohomekit.controller import Controller
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
from aiohomekit.characteristic_cache import (
    CharacteristicCacheFile,
    # CharacteristicCacheMemory,
    # StorageLayout
)
# from aiohomekit.exceptions import HomeKitException
# from aiohomekit.zeroconf import ZeroconfServiceListener
# from aiohomekit import const
# from aiohomekit.model import CharacteristicsTypes


@asynccontextmanager
async def get_controller(zeroconf: AsyncZeroconf, pairings_file_path: str, charmap_file_path: str) -> AsyncIterator[Controller]:
    controller = Controller(
        async_zeroconf_instance=zeroconf,
        char_cache=CharacteristicCacheFile(Path(charmap_file_path)),
    )
    controller.load_data(pairings_file_path)

    # TODO: standartize pairings and charmap file names, injection, and implementation

    async with zeroconf: # TODO: check if this is needed UPD: just calls .async_close()
        # listener = ZeroconfServiceListener()
        # browser = AsyncServiceBrowser(
        #     zeroconf.zeroconf,
        #     [
        #         "_hap._tcp.local.",
        #         "_hap._udp.local.",
        #     ],
        #     listener=listener,
        # )

        # bleak_logger = logging.getLogger("bleak")
        # bleak_logger.setLevel(logging.CRITICAL)
        # import warnings
        # warnings.filterwarnings("ignore")

        async with controller: # TODO: check if this is needed UPD: just calls async_start and async_stop
            try:
                controller.load_data(pairings_file)
            except Exception:
                # logger.exception(f"Error while loading {args.file}")
                raise SystemExit


            yield controller

        # print("CLI | Controller closed ok")
        # await browser.async_cancel()
        # print("CLI | Browser closed ok")
