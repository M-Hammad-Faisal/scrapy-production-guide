"""Item loaders: cleaning lives here, validation lives in pipelines.

Why split them? A loader turns messy raw text into the right *types*. A pipeline then asks "is
this record acceptable?" Keeping the two apart means a bad value is rejected by a named rule
you can test and count, not hidden inside a clever cleaning function.
"""

from itemloaders.processors import MapCompose, TakeFirst
from scrapy.loader import ItemLoader

from crawlers.utils.parsing import (
    clean_text,
    parse_availability,
    parse_price,
    parse_rating,
)


class BookLoader(ItemLoader):
    default_output_processor = TakeFirst()

    title_in = MapCompose(clean_text)
    category_in = MapCompose(clean_text)
    description_in = MapCompose(clean_text)
    upc_in = MapCompose(clean_text)
    price_gbp_in = MapCompose(parse_price)
    rating_in = MapCompose(parse_rating)
    availability_in = MapCompose(parse_availability)
