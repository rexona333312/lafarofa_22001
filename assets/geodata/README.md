# Geographic map sources

`map_geographic` and `map_annotations` with required `params.geo` use real longitude and latitude. Legacy image-map overlays have been removed.

- `countries.geojson`: Natural Earth 1:50m, modern country polygons. Public-domain dataset, simplified properties `code` (ADM0_A3) and `name`. Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_50m_admin_0_countries.geojson . Natural Earth terms: https://www.naturalearthdata.com/about/terms-of-use/ . Downloaded 2026-10-20. This is not a historical border dataset.
- Imagery: NASA GIBS, `BlueMarble_ShadedRelief_Bathymetry`, August 2004 composite, approximately 500 m. https://gibs.earthdata.nasa.gov/ and https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/ . This is an illustrative global satellite composite, not contemporaneous footage of historical events. No API key required. Maximum native tile zoom 8; close views overzoom the imagery.
- Elevation: Mapzen Terrain Tiles, Terrarium RGB. https://registry.opendata.aws/terrain-tiles/ . Source agency attribution and license details: https://github.com/tilezen/joerd/blob/master/docs/attribution.md . Sources include SRTM, GMTED and national elevation datasets. The template keeps provider attribution visible.

`tile_cache/` contains downloaded tiles. The local Node tile service fetches only fixed provider URLs, verifies image signatures, limits concurrency to four downloads and retries transient failures. Cached images are reused across render jobs. A new camera region or zoom may require internet on its first render. The renderer fails explicitly when a required tile cannot be loaded; it does not replace missing terrain with an invented map.

Modern country highlighting uses Natural Earth country codes, e.g. CHE, DEU, FRA. Arbitrary regions use `geo.regions:[{points:[[longitude,latitude],...],label,start_frame,draw_frames,color}]`. These supplied coordinates must come from the current script's checked geography; approximate redoubt/occupation shapes are not historical evidence. The API rejects `historical_year` as an automatic border conversion. `geo.date` is only an onscreen caption.
