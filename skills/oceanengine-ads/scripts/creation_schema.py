"""Client-side creation schema; gateway enforces ownership and game identity."""
import math
import re

OPS={"new_project","new_ad","new_campaign","creation_status","resume_creation"}

MAX_VIDEOS_PER_AD = 30


def number(value, lower, upper, decimals):
    if (type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper
            or abs(value * 10 ** decimals - round(value * 10 ** decimals)) > 1e-5):
        raise ValueError('Numeric value outside supported range or precision.')


def ids(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 20
            or any(type(x) is not int or x <= 0 for x in value) or len(set(value)) != len(value)):
        raise ValueError('Use 1-20 distinct positive integer IDs.')


def text(value, limit=100):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError('A non-empty text field within the length limit is required.')


def video_specs(ad):
    fields = {'video_id', 'cover_id', 'orientation'}
    required = {'video_id', 'cover_id'}
    if 'videos' in ad:
        if fields & ad.keys():
            raise ValueError('Use either videos or the single-video fields.')
        videos = ad['videos']
    else:
        videos = [{key: ad[key] for key in fields if key in ad}]
    if not isinstance(videos, list) or not 1 <= len(videos) <= MAX_VIDEOS_PER_AD:
        raise ValueError(f'Provide 1–{MAX_VIDEOS_PER_AD} videos per ad.')
    seen = set()
    for video in videos:
        if not isinstance(video, dict) or set(video) - fields or not required <= video.keys():
            raise ValueError('Each video requires video_id and cover_id and accepts optional orientation.')
        text(video['video_id'], 256)
        text(video['cover_id'], 256)
        if video.get('orientation', 'VERTICAL') not in ('VERTICAL', 'HORIZONTAL'):
            raise ValueError('Unsupported video orientation.')
        if video['video_id'] in seen:
            raise ValueError('Video IDs must be distinct within one ad.')
        seen.add(video['video_id'])
    return videos


def carousel_request(args):
    if not isinstance(args, dict) or set(args) - {'images', 'audio_id', 'file_name'}:
        raise ValueError('Carousel takes images, optional audio_id and file_name.')
    images = args.get('images')
    if not isinstance(images, list) or not 1 <= len(images) <= 35:
        raise ValueError('Provide 1–35 carousel images in display order.')
    for image in images:
        if not isinstance(image, dict) or set(image) != {'image_id'}:
            raise ValueError('Each carousel image requires image_id.')
        text(image['image_id'], 256)
    for field in ('audio_id', 'file_name'):
        if field in args:
            text(args[field], 256)


def ad_materials(ad):
    materials = {}
    if {'video_id', 'cover_id', 'orientation', 'videos'} & ad.keys():
        materials['video_material_list'] = video_specs(ad)
    if 'image_material_list' in ad:
        images = ad['image_material_list']
        if not isinstance(images, list) or not 1 <= len(images) <= 10:
            raise ValueError('Provide 1–10 image materials.')
        modes = {'CREATIVE_IMAGE_MODE_SMALL', 'CREATIVE_IMAGE_MODE_LARGE', 'CREATIVE_IMAGE_MODE_LARGE_VERTICAL'}
        for item in images:
            if not isinstance(item, dict) or set(item) != {'image_mode', 'images'} or item['image_mode'] not in modes:
                raise ValueError('Each image material requires a supported image_mode and images.')
            if not isinstance(item['images'], list) or len(item['images']) != 1:
                raise ValueError('Each image material takes exactly one image.')
            carousel_request({'images': item['images']})
        materials['image_material_list'] = images
    if 'carousel_material_list' in ad:
        carousels = ad['carousel_material_list']
        if not isinstance(carousels, list) or not 1 <= len(carousels) <= 10:
            raise ValueError('Provide 1–10 carousel materials.')
        for item in carousels:
            if (not isinstance(item, dict) or set(item) != {'carousel_id'}
                    or not isinstance(item['carousel_id'], str) or not re.fullmatch('[1-9][0-9]{0,18}', item['carousel_id'])):
                raise ValueError('Each carousel material requires carousel_id as a decimal string.')
        materials['carousel_material_list'] = carousels
    if not materials:
        raise ValueError('Provide video, image or carousel materials.')
    return materials


# IAA retrieval windows accepted by the gateway; keep in step with the server.
ROI_MODES = ('7d', '30d')

def validate(op, args):
    if op not in OPS or not isinstance(args, dict):raise ValueError('Unknown creation operation.')
    if not re.fullmatch('[A-Za-z0-9_-]{8,80}', str(args.get('creation_id', ''))):raise ValueError('Stable creation_id required.')
    if op in ('creation_status', 'resume_creation'):
        if set(args) != {'creation_id'}:raise ValueError('Use creation_id only.')
        return
    allowed = {'creation_id'} | ({'project'} if op in ('new_project', 'new_campaign') else set()) | ({'ad'} if op in ('new_ad', 'new_campaign') else set()) | ({'project_id'} if op == 'new_ad' else set())
    if set(args) != allowed:raise ValueError('Unexpected or missing creation fields.')
    if 'project' in args:
        p = args['project']
        if not isinstance(p, dict) or set(p) - {'name', 'budget', 'roi_goal', 'gender', 'roi_mode'} or not {'name','budget','roi_goal'} <= set(p):raise ValueError('Project takes name, budget, roi_goal and optional gender and roi_mode.')
        text(p['name']);number(p['budget'], 300, 999999.99, 2);number(p['roi_goal'], .01, 5, 4)
        if 'roi_mode' in p and p['roi_mode'] not in ROI_MODES:raise ValueError('Unsupported roi_mode. Use 7d or 30d for IAA ROI.')
        if p.get('gender', 'NONE') not in ('NONE','GENDER_MALE','GENDER_FEMALE'):raise ValueError('Unsupported gender targeting.')
    if op == 'new_ad':ids([args['project_id']])
    if 'ad' in args:
        a = args['ad']
        if not isinstance(a, dict) or set(a) - {'name', 'video_id', 'cover_id', 'titles', 'orientation', 'product_image_id', 'videos', 'image_material_list', 'carousel_material_list'} or 'name' not in a:
            raise ValueError('Ad requires a name and valid material fields.')
        text(a['name'])
        ad_materials(a)
        if 'product_image_id' in a:text(a['product_image_id'],256)
        if 'titles' in a:
            if not isinstance(a['titles'], list) or not 1 <= len(a['titles']) <= 10:raise ValueError('Provide 1–10 titles.')
            for title in a['titles']:text(title, 55)
