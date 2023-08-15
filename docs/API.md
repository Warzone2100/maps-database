# Maps Database API

Origin: `https://maps.wz2100.net/`

## Fetching the Map Database

### List the Full Map Database

The full map database is available in (paginated) JSON format.

The first page is available at:

**`GET /api/v1/full.json`**

Subsequent pages can be obtained via the instructions in [Handling Pagination](handling-pagination).

> **NOTE: It is strongly recommended that you cache the responses from these queries.**

##### Handling Pagination:

Check the `links` property of the root JSON object for a `next` key. Its value will be the URL of the next page.

If a page does not have a `links.next` value, it is the final page of JSON data.

##### Example Response (JSON):

```json
{
  "type": "wz2100.mapdatabase.full.v1",
  "id": "full-page-1",
  "links": {
    "self": "/api/v1/full.json",
    "next": "/api/v1/full/page/2.json"
  },
  "asset-url-templates": {
    "download": ["https://github.com/Warzone2100/maps-{{download/repo}}/releases/download/{{download/path}}"],
    "preview": {
      "2d": "https://maps-assets.wz2100.net/v1/maps/{{download/hash}}/preview.png"
    },
    "readme": {
      "en": "https://maps-assets.wz2100.net/v1/maps/{{download/hash}}/readme.md"
    },
    "info": "https://maps-assets.wz2100.net/v1/maps/{{download/hash}}.json"
  },
  "maps": [
    {
      // <map info object (see below)>
    }
  ]
}
```

##### JSON Response Format:

- `type`: `wz2100.mapdatabase.full.v1`
- `version`: The version of this page (string), which can be stored alongside any cache of this data and compared versus the value returned by the `versions` API
- `links`: An object containing `self`, `next` (optional), and `prev` (optional) members
- `asset-url-templates`: An [Asset URL Templates](#asset-url-templates) object
- `maps`: An array of [Map Info JSON](#map-info-json) objects

##### Asset URL Templates:

- `download`: An array containing 1+ [Map Database URL templates](#map-database-url-templates) for generating a download URL (the primary, followed by any mirrors)
- `preview`: An object containing:
  - `2d`: A [Map Database URL template](#map-database-url-templates) for generating a 2d map preview image URL
- `readme`: An object containing:
  - `en`: A [Map Database URL template](#map-database-url-templates) for generating a URL to access the English readme for a map
  > Note: A readme may not be present - expect that this can and will return 404
- `info`: A [Map Database URL template](#map-database-url-templates) for generating a URL to access the map info json (by a hash)

### Get Database Version Info

It is **strongly** recommended that you cache the responses from the [List the Full Map Database](#list-the-full-map-database) queries.

Each JSON response above contains a `version` field, which can be stored alongside the cached data.

You can then request the latest version info for all Full Map Database pages from:

**`GET /api/v1/versions.json`**

##### Example Response (JSON):

```json
{
  "type": "wz2100.mapdatabase.versions.v1",
  "id": "versions",
  "versions": [
    {
      "page": "/api/v1/full.json",
      "version": "2023-01-01 HH:MM:SS"
    }
  ]
}
```

## Accessing Map Info

> Note: You should be prepared for these APIs to return a 30x redirect.

### Lookup a Map (by Hash)

Get the map info, by hash

**`GET /api/v1/maps/<full hash>/info.json`**

Returns a [Map Info JSON](#map-info-json) object.

### Get a 2D Map Preview (by Hash)

Get the 2d preview of a map, by hash

**`GET /api/v1/maps/<full hash>/preview.png`**

### Get the README for a Map (by Hash)

Get a supplementary description for a map (if available), by hash

> NOTE: This may ultimately return 404 if the map author / uploader did not provide a supplementary description.

**`GET /api/v1/maps/<full hash>/readme.md`**


## Additional Details

### Map Database URL Templates

Anything within `{{ }}` defines a replacement via JSON Pointer ([RFC 6901](http://tools.ietf.org/html/rfc6901)), to look up values in a Map Info object.

> (NOTE: The starting `/` is omitted, and should be prepended when using most JSON Pointer libraries.)

##### Example:

If the template is:
`https://github.com/Warzone2100/maps-{{download/repo}}/releases/download/{{download/path}}`

Given the example in the [Map Info JSON](#map-info-json) section:
1. `{{download/repo}}` would look up `/download/repo` in the Map Info object, returning `8p`
2. `{{download/path}}` would look up `/download/path` in the Map Info object, returning `v1/8p-MyMap.wz`

Replacement would then yield a download URL of:
`https://github.com/Warzone2100/maps-8p/releases/download/v1/8p-MyMap.wz`

##### Example Javascript:

```html
<script src="path/to/jsonpointer.js"></script>
```
(see: [jsonpointer.js](https://github.com/alexeykuzmin/jsonpointer.js/blob/master/src/jsonpointer.js))
```js
let mapDatabaseURLTemplateReplacement(str, map_info_obj) => {
  return str.replace(/{{(.+?)}}/g, (_,g1) => {
    var i = jsonpointer.get(map_info_obj, '/' + g1.trim());
    if (typeof i === 'undefined') {
      return g1;
    }
    return i;
  })
}
```

### Map Info JSON

##### Key Fields:

- **`name`** (string)
  The name of the map
- **`slots`** (integer)
  The number of player slots
  Value: Between `2` and `10`
- **`author`** (string OR array of strings)
  The author(s) of the map
  May be either a string:
  `"author": "AuthorName"`
  Or an array of strings (if multiple authors):
  `"author": ["Author1", "Author2"]`
- **`license`** (string)
  An [SPDX License Expression](https://spdx.org/licenses/) describing the license of the map
- **`size`** (an object)
  Containing:
  - **`w`** (integer) - the width of the map (in tiles)
  - **`h`** (integer) - the height of the map (in tiles)
- **`scavs`** (integer)
- **`oilWells`** (integer)
  The number of oil wells on the map
- **`player`** (object)
  The [player counts / balance info](#player-counts-balance-info)
- **`hq`** (array)
  Containing an array for each player that specifies that player's HQ location (in _map_ coordinates, `[x,y]`)
- **`download`** (object)
  The download / package information

##### Player Counts / Balance Info:

The player counts / balance info object contains many keys:

- **`units`** (object)
- **`structs`** (object)
- **`resourceExtr`** (object)
- **`pwrGen`** (object)
- **`regFact`** (object)
- **`vtolFact`** (object)
- **`cyborgFact`** (object)
- **`researchCent`** (object)
- **`defStruct`** (object)

Each key has as its value an object with the following properties:

- **`eq`** (boolean)
  Whether the particular property is *equal* / balanced among _all_ players
  (Note: This includes both the number and the _type_, in many cases - such as for `"units"`)
- **`min`** (integer)
  The minimum number of this property that a player will have on the map
- **`max`** (integer)
  The maximum number of this property that a player will have on the map

> NOTE: In certain cases (like with `"units"`) `min == max` does not necessarily imply `eq` will be `True` (as the *type* of units may differ). If you care about *balance*, you probably want to check `eq`.


##### Example:

```json
{
  "name": "MyMap",
  "slots": 8,
  "tileset": "arizona",
  "author": "Originator",
  "license": "CC0-1.0",
  "created": "2012-06-01",
  "size": {
    "w": 200,
    "h": 200
  },
  "scavs": 0,
  "oilWells": 320,
  "player": {
    "units": {
      "eq": true,
      "min": 4,
      "max": 4
    },
    "structs": {
      "eq": true,
      "min": 4,
      "max": 61
    },
    "resourceExtr": {
      "eq": true,
      "min": 40,
      "max": 40
    },
    "pwrGen": {
      "eq": true,
      "min": 10,
      "max": 10
    },
    "regFact": {
      "eq": true,
      "min": 0,
      "max": 0
    },
    "vtolFact": {
      "eq": true,
      "min": 0,
      "max": 0
    },
    "cyborgFact": {
      "eq": true,
      "min": 0,
      "max": 0
    },
    "researchCent": {
      "eq": true,
      "min": 0,
      "max": 0
    },
    "defStruct": {
      "eq": true,
      "min": 0,
      "max": 0
    }
  },
  "hq": [
    [33,13],
    [76,13],
    [149,13],
    [192,13],
    [8,187],
    [51,187],
    [124,187],
    [167,187]
  ],
  "download": {
    "type": "jsonv2",
    "repo": "8p",
    "path": "v1/8p-MyMap.wz",
    "uploaded": "2023-05-01",
    "hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "size": 12345
  }
}
```
