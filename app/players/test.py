import asyncio
from typing import Callable, Coroutine, List, Any


async def run_player_test(player_function: Callable[[str], Coroutine[Any, Any, tuple]], test_urls: List[str]):
    for test_url in test_urls:
        print("-" * 50)
        print(f"Testing Player: {player_function.__name__}")
        print(f"Testing URL: {test_url}")

        try:
            video_link, video_quality, video_headers = await player_function(test_url)

            if video_link:
                print("\n--- SUCCESS ---")
                print(f"URL: {video_link}")
                print(f"Quality: {video_quality}")
                print(f"Headers: {video_headers}")
            else:
                print("\n--- FAILURE ---")
                print("Function returned None, but no exception was raised.")
        except Exception as e:
            print(f"\n--- CRITICAL FAILURE ---")
            print(f"An exception occurred during the test: {e}")

        print("-" * 50)
        print()


def run_tests(player_function: Callable, test_urls: List[str]):
    asyncio.run(run_player_test(player_function, test_urls))