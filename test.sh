#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8000"
QUERY="пшеничная мука"
SIZE=100
PAGE=1

echo '['
first=true

while true; do
    response=$(curl -fsS --get "$BASE/api/search" \
        --data-urlencode "q=$QUERY" \
        --data-urlencode "page=$PAGE" \
        --data-urlencode "size=$SIZE")

    count=$(jq '(.items // .products // .results // []) | length' <<< "$response")
    echo "page=$PAGE products=$count" >&2

    (( count == 0 )) && break

    for sku in $(jq -r '
        (.items // .products // .results // [])[] |
        .skuCode // .sku // .code
    ' <<< "$response"); do

        product=$(curl -fsS "$BASE/api/catalog/product/$sku")

        if [[ "$first" == true ]]; then
            first=false
        else
            echo ','
        fi

        jq '{
            name,
            article,
            regularPrice,
            discountPrice,
            unit,
            nutrition,
            ingredients,
            characteristics,
            description,
            web_url
        }' <<< "$product"
    done

    (( count < SIZE )) && break
    ((PAGE++))
done

echo ']'
