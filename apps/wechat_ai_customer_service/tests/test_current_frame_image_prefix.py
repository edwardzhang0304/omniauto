"""0.9.74 source integration: reviewed synthetic cases, no Windows acceptance.

Copied from the reviewed Chejin boundary tests. Real incident fixtures and
Worker/HTTP tests stay in Chejin; no customer captures are published here.
"""
from pathlib import Path
import sys
import pytest
from PIL import Image, ImageDraw, ImageEnhance
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as s

from test_frame_avatars import synthetic_frame, draw_avatar, row
from apps.wechat_ai_customer_service.optional_plugins.vision.capture import wechat

def textured_image(draw, left, top, right, bottom):
    for y in range(top, bottom, 8):
        for x in range(left, right, 8):
            tone = 35 if ((x-left+y-top)//8) % 2 else 220
            draw.rectangle((x,y,min(x+7,right-1),min(y+7,bottom-1)),fill=(tone,150,80))

def prefix_scene(old_role='customer', next_role='customer', old_type='text',
                 next_type='image', *, next_top=208, history=False, dpi=1):
    image,layout=synthetic_frame();draw=ImageDraw.Draw(image)
    old_x=400 if old_role=='customer' else 930
    old_left=470 if old_role=='customer' else 680
    draw_avatar(image,old_x,82)
    if old_type=='image': textured_image(draw,old_left,90,old_left+200,196)
    else: draw.rectangle((old_left,90,old_left+200,195),fill=(130,220,150))
    rows=[row('顶部旧消息',109,left=old_left,right=old_left+180)]
    if history:
        image.paste('white',(470,137,1000,196))
        draw_avatar(image,400,148)
        draw.rectangle((470,148,670,188),fill=(130,220,150))
        rows.append(row('唯一已入库的历史锚点',157,left=482,right=650))
    next_x=400 if next_role=='customer' else 930
    next_left=470 if next_role=='customer' else 680
    draw_avatar(image,next_x,next_top)
    if next_type=='image': textured_image(draw,next_left,next_top,next_left+200,next_top+136)
    elif next_type=='voice':
        draw.rectangle((next_left,next_top,next_left+200,next_top+40),fill=(130,220,150))
        rows.append(row('6"',next_top+9,left=next_left+12,right=next_left+62))
    else:
        draw.rectangle((next_left,next_top,next_left+200,next_top+40),fill=(130,220,150))
        rows.append(row('这条完整消息必须保留',next_top+9,left=next_left+12,right=next_left+188))
    draw_avatar(image,400,430)
    rows.append(row('后续完整客户问题',439,left=470,right=800))
    if dpi!=1:
        image=image.resize((round(image.width*dpi),round(image.height*dpi)))
        layout={**layout,'dpi_scale':dpi,
                'message_viewport_bounds':[round(v*dpi) for v in layout['message_viewport_bounds']],
                'input_bounds':[round(v*dpi) for v in layout['input_bounds']]}
        rows=[{k:(v*dpi if k in {'top','bottom','left','right','center_x','center_y'} else v) for k,v in r.items()} for r in rows]
    return image,layout,rows

@pytest.mark.parametrize('role', ['customer', 'self'])
@pytest.mark.parametrize('dpi', [1, 1.25, 1.5])
def test_complete_image_survives_excluded_prefix(role, dpi):
    image, layout, rows = prefix_scene(old_role=role, next_role=role, dpi=dpi)
    original = image.tobytes()
    table = s.frame_avatars.avatar_table(image, layout)
    diagnostics = []
    bubbles = wechat.detect_visual_image_bubbles(
        image, side_filter='all', message_viewport_bounds=layout['message_viewport_bounds'],
        readable_top=table['readable_top'], diagnostics=diagnostics)
    expected = [(470 if role == 'customer' else 680)*dpi, 208*dpi,
                (670 if role == 'customer' else 880)*dpi, 344*dpi]
    def coverage(bubble):
        rect = bubble['bounds']
        overlap = max(0,min(rect[2],expected[2])-max(rect[0],expected[0])) * max(0,min(rect[3],expected[3])-max(rect[1],expected[1]))
        return overlap / ((expected[2]-expected[0])*(expected[3]-expected[1]))
    assert any(coverage(b) > .95 for b in bubbles), (bubbles, diagnostics)
    assert image.tobytes() == original
