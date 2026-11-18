"""Portable UBMAX PRO creation input contract (not the upstream payload)."""

EXAMPLE = {
    'name': 'UBMAX PRO IAA test',
    'budget': 300,
    'roi': 0.8,
    'roi_mode': '7d',
    'videos': [{'video_id': 'REPLACE_VIDEO_ID', 'video_cover_id': 'REPLACE_COVER_ID'}],
    'titles': ['Example shared title'],
}
FIELDS = frozenset(EXAMPLE)
CONFIRM = 'accept_scheduled_then_pause'
IMMEDIATE_CONFIRM = 'accept_create_then_pause'


def validate_creation(args, *, submit=False):
    if not isinstance(args, dict):
        raise ValueError('UBMAX PRO requires a flat JSON object.')
    expected = FIELDS | {'product_info'} | ({CONFIRM, IMMEDIATE_CONFIRM} if submit else set())
    missing = sorted(FIELDS - args.keys())
    unexpected = sorted(args.keys() - expected)
    if missing or unexpected:
        details = (['missing: ' + ', '.join(missing)] if missing else []) + (
            ['unexpected: ' + ', '.join(unexpected)] if unexpected else [])
        raise ValueError('UBMAX PRO requires a flat creation JSON; ' + '; '.join(details)
                         + '. See ubmax-pro-schema.')
    if submit:
        confirmations = [args.get(key) is True for key in (CONFIRM, IMMEDIATE_CONFIRM)]
        if sum(confirmations) != 1 or any(key in args and args[key] is not True for key in (CONFIRM, IMMEDIATE_CONFIRM)):
            raise ValueError('Use exactly one confirmation: accept_create_then_pause=true for immediate long-term scheduling, or accept_scheduled_then_pause=true for legacy future scheduling.')
    if 'product_info' in args:
        validate_product_info(args['product_info'])
    import math
    if not isinstance(args['name'],str) or not 1 <= len(args['name'].strip()) <= 80 or args['name'] != args['name'].strip() or not args['name'].isprintable():
        raise ValueError('Specify a project name of 1-80 characters.')
    if args['roi_mode'] not in ('7d','30d'):raise ValueError('Use IAA 7d or 30d ROI mode.')
    for k,lo,hi in [('budget',100,100000),('roi',0.01,100)]:
        v=args[k]
        if type(v) not in (int,float) or not lo <= v <= hi or not math.isfinite(v) or round(v,2)!=v:
            raise ValueError(f'UBMAX PRO {k} must be numeric in {lo}-{hi}, with at most two decimals.')
    videos=args['videos']
    if not isinstance(videos,list) or not 1<=len(videos)<=30:raise ValueError('Provide 1-30 videos with covers.')
    for video in videos:
        if not isinstance(video,dict) or set(video)!={'video_id','video_cover_id'} or any(
            not isinstance(v,str) or not 1<=len(v)<=256 or any(c.isspace() for c in v) for v in video.values()):
            raise ValueError('Video entries accept video_id and video_cover_id only; per-video titles are not supported.')
    titles=args['titles']
    if not isinstance(titles,list) or not 1<=len(titles)<=30 or any(
        not isinstance(t,str) or not 10<=sum(1 if c.isascii() else 2 for c in t.strip())<=110 for t in titles):
        raise ValueError('Provide 1-30 shared project titles, each 5-55 characters.')


def validate_product_info(product):
    fields = {'titles', 'image_ids', 'selling_points', 'product_name_type',
              'product_image_type', 'product_selling_point_type'}
    if (not isinstance(product, dict) or set(product) - fields
            or not {'titles', 'image_ids', 'selling_points'} <= set(product)):
        raise ValueError('product_info requires titles, image_ids and selling_points.')
    for key in ('product_name_type', 'product_image_type', 'product_selling_point_type'):
        if key in product and product[key] != 'CUSTOM':
            raise ValueError('Explicit product_info supports CUSTOM product fields.')
    for key, limit, minimum, maximum in (('titles', 1, 1, 20),
                                         ('image_ids', 10, 1, 256),
                                         ('selling_points', 10, 6, 9)):
        values = product[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= limit
                or any(not isinstance(value, str) or value != value.strip() or not value.isprintable()
                       or not minimum <= len(value) <= maximum for value in values)):
            raise ValueError(f'product_info.{key} requires 1–{limit} values of {minimum}–{maximum} characters.')
