"""
Test script for Prison School OVA search scenario.

Run with:
    python -m pytest tests/test_prison_school_ova.py -v -s

Or run directly:
    python tests/test_prison_school_ova.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up minimal environment before importing app modules
import os

os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("PROWLARR_URL", "http://localhost:9696")
os.environ.setdefault("PROWLARR_API_KEY", "test")
os.environ.setdefault("DATA_DIR", str(Path(__file__).parent.parent / "data"))


async def test_thexem_api_connection():
    """Test that we can connect to TheXEM API with proper headers."""
    import httpx

    headers = {
        "User-Agent": "AnimeSonarrProxy/1.0 (https://github.com/WarheadTaylor/AnimeSonarrProxy)"
    }

    # Test the allNames endpoint
    url = "https://thexem.info/map/allNames"
    params = {"origin": "tvdb", "defaultNames": "1"}

    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        response = await client.get(url, params=params)
        print(f"TheXEM allNames response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"TheXEM allNames result: {data.get('result')}")
            print(f"Number of shows: {len(data.get('data', {}))}")

            # Check if Prison School (TVDB 293267) is in the data
            tvdb_data = data.get("data", {})
            if "293267" in tvdb_data or 293267 in tvdb_data:
                print(
                    f"Prison School names: {tvdb_data.get('293267') or tvdb_data.get(293267)}"
                )
            else:
                print("Prison School (TVDB 293267) NOT found in TheXEM allNames")
                # Print a sample of what we got
                sample_keys = list(tvdb_data.keys())[:5]
                print(f"Sample TVDB IDs in TheXEM: {sample_keys}")
        else:
            print(f"Error response: {response.text[:500]}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"


async def test_thexem_map_all_for_prison_school():
    """Test if Prison School has episode mappings in TheXEM."""
    import httpx

    headers = {
        "User-Agent": "AnimeSonarrProxy/1.0 (https://github.com/WarheadTaylor/AnimeSonarrProxy)"
    }

    url = "https://thexem.info/map/all"
    params = {"id": 293267, "origin": "tvdb"}

    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        response = await client.get(url, params=params)
        print(f"\nTheXEM map/all for Prison School status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Result: {data.get('result')}")
            print(f"Message: {data.get('message')}")
            mappings = data.get("data", [])
            print(f"Number of episode mappings: {len(mappings)}")
            if mappings:
                print(f"First mapping: {mappings[0]}")
        else:
            print(f"Error or not found: {response.text[:200]}")


async def test_anime_offline_db_for_prison_school():
    """Test if Prison School is in anime-offline-database."""
    from app.services.anime_db import anime_db

    # Initialize the database
    await anime_db.initialize()

    anime = anime_db.get_by_tvdb_id(293267)
    if anime:
        print(f"\nFound Prison School in anime-offline-database:")
        print(f"  Title: {anime.get('title')}")
        print(f"  Synonyms: {anime.get('synonyms', [])[:5]}")
        print(f"  Sources: {anime.get('sources', [])[:3]}")
    else:
        print("\nPrison School (TVDB 293267) NOT found in anime-offline-database")

        # Try searching by title
        matches = anime_db.search_by_title("Prison School", limit=3)
        if matches:
            print("But found by title search:")
            for m in matches:
                print(f"  - {m.get('title')}")
                sources = m.get("sources", [])
                tvdb_sources = [s for s in sources if "thetvdb" in s]
                print(f"    TVDB sources: {tvdb_sources}")


async def test_thexem_client():
    """Test TheXEM client from our codebase."""
    from app.services.thexem import thexem_client

    print("\n--- Testing TheXEM Client ---")

    # Test get_names_by_tvdb_id
    names = await thexem_client.get_names_by_tvdb_id(293267)
    if names:
        print(f"Names for TVDB 293267: {names}")
    else:
        print("No names found via thexem_client.get_names_by_tvdb_id(293267)")

    # Test get_all_mappings
    mappings = await thexem_client.get_all_mappings(293267, origin="tvdb")
    if mappings:
        print(f"Found {len(mappings)} episode mappings")
    else:
        print("No episode mappings found")


async def test_mapping_service():
    """Test the mapping service for Prison School."""
    from app.services.mapping import mapping_service
    from app.services.anime_db import anime_db

    print("\n--- Testing Mapping Service ---")

    # Initialize services
    await anime_db.initialize()
    await mapping_service.initialize()

    # Try to get mapping for Prison School
    mapping = await mapping_service.get_mapping(293267)

    if mapping:
        print(f"Found mapping for TVDB 293267:")
        print(f"  TVDB ID: {mapping.tvdb_id}")
        print(f"  AniDB ID: {mapping.anidb_id}")
        print(f"  AniList ID: {mapping.anilist_id}")
        print(f"  Titles: {mapping.titles}")
        print(f"  Search titles: {mapping.get_search_titles()}")
    else:
        print("No mapping found for TVDB 293267")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Prison School OVA Search Scenario")
    print("=" * 60)

    print("\n[1] Testing TheXEM API connection...")
    try:
        await test_thexem_api_connection()
        print("PASSED")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n[2] Testing TheXEM map/all for Prison School...")
    try:
        await test_thexem_map_all_for_prison_school()
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n[3] Testing anime-offline-database...")
    try:
        await test_anime_offline_db_for_prison_school()
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n[4] Testing TheXEM client...")
    try:
        await test_thexem_client()
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n[5] Testing Mapping Service...")
    try:
        await test_mapping_service()
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n" + "=" * 60)
    print("Tests complete!")


if __name__ == "__main__":
    asyncio.run(main())
