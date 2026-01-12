# Mapping Information

## Single
You will need the id / identifier of the show e.g. tvdb-id for American Dad! is 73141
the origin is the name of the site/entity the episode, season (and/or absolute) numbers are based on

https://thexem.info/map/single?id=&origin=&episode=&season=&absolute=

episode, season and absolute are all optional but it wont work if you don't provide either episode and season OR absolute in addition you can provide destination as the name of the wished destination, if not provided it will output all available

When a destination has two or more addresses another entry will be added as _ ... for now the second address gets the index "2" (the first index is omitted) and so on

https://thexem.info/map/single?id=7529&origin=anidb&season=1&episode=2&destination=trakt

{
"result":"success",
 "data":{
        "trakt":  {"season":1,"episode":3,"absolute":3},
        "trakt_2":{"season":1,"episode":4,"absolute":4}
        },
 "message":"single mapping for 7529 on anidb."
}

## All

Basically same as "single" just a little easier
The origin address is added into the output too!!

https://thexem.info/map/all?id=7529&origin=anidb

{"result":"success","data":[{"scene":{"season":1,"episode":1,"absolute":1},"tvdb":{"season":1,"episode":1,"absolute":1},"tvdb_2":{"season":1,"episode":2,"absolute":2},"rage":{"season":1,"episode":1,"absolute":1},"trakt":{"season":1,"episode":1,"absolute":1},"trakt_2":{"season":1,"episode":2,"absolute":2},"anidb":{"season":1,"episode":1,"absolute":1}},{"scene":{"season":1,"episode":2,"absolute":2},"tvdb":{"season":1,"episode":3,"absolute":3},"tvdb_2":{"season":1,"episode":4,"absolute":4},"rage":{"season":1,"episode":2,"absolute":2},"trakt":{"season":1,"episode":3,"absolute":3},"trakt_2":{"season":1,"episode":4,"absolute":4},"anidb":{"season":1,"episode":2,"absolute":2}},{"scene":{"season":1,"episode":3,"absolute":3},"tvdb":{"season":1,"episode":5,"absolute":5},"tvdb_2":{"season":1,"episode":6,"absolute":6},"rage":{"season":1,"episode":3,"absolute":3},"trakt":{"season":1,"episode":5,"absolute":5},"trakt_2":{"season":1,"episode":6,"absolute":6},"anidb":{"season":1,"episode":3,"absolute":3}},{"scene":{"season":1,"episode":4,"absolute":4},"tvdb":{"season":1,"episode":7,"absolute":7},"tvdb_2":{"season":1,"episode":8,"absolute":8},"rage":{"season":1,"episode":4,"absolute":4},"trakt":{"season":1,"episode":7,"absolute":7},"trakt_2":{"season":1,"episode":8,"absolute":8},"anidb":{"season":1,"episode":4,"absolute":4}},{"scene":{"season":1,"episode":5,"absolute":5},"tvdb":{"season":1,"episode":9,"absolute":9},"tvdb_2":{"season":1,"episode":10,"absolute":10},"rage":{"season":1,"episode":5,"absolute":5},"trakt":{"season":1,"episode":9,"absolute":9},"trakt_2":{"season":1,"episode":10,"absolute":10},"anidb":{"season":1,"episode":5,"absolute":5}},{"scene":{"season":1,"episode":6,"absolute":6},"tvdb":{"season":1,"episode":11,"absolute":11},"tvdb_2":{"season":1,"episode":12,"absolute":12},"rage":{"season":1,"episode":6,"absolute":6},"trakt":{"season":1,"episode":11,"absolute":11},"trakt_2":{"season":1,"episode":12,"absolute":12},"anidb":{"season":1,"episode":6,"absolute":6}},{"scene":{"season":1,"episode":7,"absolute":7},"tvdb":{"season":1,"episode":13,"absolute":13},"tvdb_2":{"season":1,"episode":14,"absolute":14},"rage":{"season":1,"episode":7,"absolute":7},"trakt":{"season":1,"episode":13,"absolute":13},"trakt_2":{"season":1,"episode":14,"absolute":14},"anidb":{"season":1,"episode":7,"absolute":7}},{"scene":{"season":1,"episode":8,"absolute":8},"tvdb":{"season":1,"episode":15,"absolute":15},"tvdb_2":{"season":1,"episode":16,"absolute":16},"rage":{"season":1,"episode":8,"absolute":8},"trakt":{"season":1,"episode":15,"absolute":15},"trakt_2":{"season":1,"episode":16,"absolute":16},"anidb":{"season":1,"episode":8,"absolute":8}},{"scene":{"season":1,"episode":9,"absolute":9},"tvdb":{"season":1,"episode":17,"absolute":17},"tvdb_2":{"season":1,"episode":18,"absolute":18},"rage":{"season":1,"episode":9,"absolute":9},"trakt":{"season":1,"episode":17,"absolute":17},"trakt_2":{"season":1,"episode":18,"absolute":18},"anidb":{"season":1,"episode":9,"absolute":9}},{"scene":{"season":1,"episode":10,"absolute":10},"tvdb":{"season":1,"episode":19,"absolute":19},"tvdb_2":{"season":1,"episode":20,"absolute":20},"rage":{"season":1,"episode":10,"absolute":10},"trakt":{"season":1,"episode":19,"absolute":19},"trakt_2":{"season":1,"episode":20,"absolute":20},"anidb":{"season":1,"episode":10,"absolute":10}},{"scene":{"season":1,"episode":11,"absolute":11},"tvdb":{"season":1,"episode":21,"absolute":21},"tvdb_2":{"season":1,"episode":22,"absolute":22},"rage":{"season":1,"episode":11,"absolute":11},"trakt":{"season":1,"episode":21,"absolute":21},"trakt_2":{"season":1,"episode":22,"absolute":22},"anidb":{"season":1,"episode":11,"absolute":11}},{"scene":{"season":1,"episode":12,"absolute":12},"tvdb":{"season":1,"episode":23,"absolute":23},"tvdb_2":{"season":1,"episode":24,"absolute":24},"rage":{"season":1,"episode":12,"absolute":12},"trakt":{"season":1,"episode":23,"absolute":23},"trakt_2":{"season":1,"episode":24,"absolute":24},"anidb":{"season":1,"episode":12,"absolute":12}},{"scene":{"season":1,"episode":13,"absolute":13},"tvdb":{"season":1,"episode":25,"absolute":25},"tvdb_2":{"season":1,"episode":26,"absolute":26},"rage":{"season":1,"episode":13,"absolute":13},"trakt":{"season":1,"episode":25,"absolute":25},"trakt_2":{"season":1,"episode":26,"absolute":26},"anidb":{"season":1,"episode":13,"absolute":13}}],"message":"full mapping for 7529 on anidb. this was a cached version"}

## All Names

Get all names xem has to offer
non optional params: origin(an entity string like 'tvdb')
optional params: season, language
- season: a season number or a list like: 1,3,5 or a compare operator like ne,gt,ge,lt,le,eq and a season number. default would return all
- language: a language string like 'us' or 'jp' default is all
- defaultNames: 1(yes) or 0(no) should the default names be added to the list ? default is 0(no)

https://thexem.info/map/allNames?origin=tvdb&season=le1

{
"result": "success",
"data": {
        "79604": ["Black-Lagoon", "ブラック・ラグーン", "Burakku Ragūn"],
        "248812": ["Dont Trust the Bitch in Apartment 23", "Don't Trust the Bitch in Apartment 23"],
        "257571": ["Nazo no Kanojo X"],
        "257875": ["Lupin III - Mine Fujiko to Iu Onna", "Lupin III Fujiko to Iu Onna", "Lupin the Third - Mine Fujiko to Iu Onna"]
        },
"message": ""
}