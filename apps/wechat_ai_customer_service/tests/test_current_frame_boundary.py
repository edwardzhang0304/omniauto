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


def calibrated_frame(image, *, scale=1, frame_id='test', ocr=None):
    geometry = dict(left=20, top=12, right=20+image.width, bottom=12+image.height,
                    width=image.width, height=image.height)
    client = dict(left=0, top=0, right=image.width, bottom=image.height, width=image.width, height=image.height)
    calibration = s.win32_ocr_layout.build_startup_layout_calibration(
        hwnd=1, process_id=1, image=image,
        ocr_items=ocr if ocr is not None else s.run_ocr(ImageEnhance.Contrast(image).enhance(1.35)),
        window_rect=geometry, client_rect=client, client_screen_origin=[20, 12],
        dpi_scale=scale, capture_mode=s.win32_ocr_layout.CAPTURE_MODE_CLIENT_AREA)
    assert calibration['executable'], calibration
    layout = s.win32_ocr_layout.build_layout_snapshot(
        hwnd=1, frame_id=frame_id, capture_mode=s.win32_ocr_layout.CAPTURE_MODE_CLIENT_AREA,
        image_size=image.size, capture_screen_origin=[20, 12], window_rect=geometry,
        client_rect=client, client_screen_origin=[20, 12], dpi_scale=scale,
        regions={k:calibration[k] for k in s.win32_ocr_layout.REQUIRED_LAYOUT_REGION_NAMES},
        anchors=calibration['anchors'], confidence=calibration['confidence'], executable=True)
    s._LAYOUT_SNAPSHOT_STORE.put(layout)
    s._LAYOUT_SNAPSHOT_ID_BY_IMAGE_ID[id(image)] = layout['layout_snapshot_id']
    return layout, geometry


@pytest.mark.parametrize('size', [(784,844), (1000,760), (1200,1000)])
@pytest.mark.parametrize('scale', [1, 1.25, 1.5])
def test_synthetic_chat_separator_is_independent_of_search_text(size, scale):
    # Constructed shell at each resolution/DPI, never a resized Windows-UAT claim.
    width,height=(round(v*scale) for v in size)
    split=round(392*scale); line=round(80*scale); thickness=max(1,round(2*scale))
    image=Image.new('RGB',(width,height),(250,250,250)); d=ImageDraw.Draw(image)
    d.rectangle((0,0,round(60*scale)-1,height-1),fill=(225,225,225))
    d.rectangle((round(60*scale),0,split-1,height-1),fill=(235,235,235))
    d.line((split,line,width-1,line), fill=(190,190,190),width=thickness)
    d.line((split,height-round(176*scale),width-1,height-round(176*scale)),fill=(190,190,190),width=thickness)
    # Move/resize only the OCR search label; chat boundary must stay identical.
    tops=[]
    for text_height in (12,20,26):
        ocr=[dict(text='搜索',left=75*scale,top=(69-text_height)*scale,right=129*scale,
                  bottom=69*scale,center_x=102*scale,center_y=(69-text_height/2)*scale,confidence=.99)]
        layout,_=calibrated_frame(image.copy(),scale=scale,ocr=ocr)
        tops.append(layout['message_viewport_bounds'][1])
    assert len(set(tops))==1, tops
    assert line < tops[0] <= line+thickness+1


@pytest.mark.parametrize('cut', [1, 10, 25, 39, 55])
@pytest.mark.parametrize('role', ['customer','self'])
def test_synthetic_partial_top_keeps_next_complete_message(cut,role):
    # Local synthetic scene: clipped old avatar + multi-line-height bubble,
    # followed by a complete independent message. No coordinate-based clicks.
    image=Image.new('RGB',(600,500),(250,250,250));d=ImageDraw.Draw(image)
    x=110 if role=='customer' else 546
    bx=158 if role=='customer' else 340
    d.rectangle((x,100-cut,x+35,135-cut),fill=(70,90,130))
    d.rectangle((bx,110-cut,bx+160,190-cut),fill=(130,220,150))
    d.rectangle((x,240,x+35,275),fill=(70,90,130))
    d.rectangle((bx,248,bx+160,282),fill=(130,220,150))
    layout={'valid':True,'dpi_scale':1,'message_viewport_bounds':[100,100,598,450],
            'layout_snapshot_id':'synthetic-top','frame_id':str(cut),'input_bounds':[100,450,598,500]}
    table=s.frame_avatars.avatar_table(image,layout)
    assert table['top_fragments'],table
    assert table['readable_top'] >= 191-cut,table
    assert s.frame_avatars.role_details(image,layout,[bx,248,bx+140,268])['role']==role
    assert not table['unresolved'],table
    rows=[dict(text='残缺旧消息',left=bx,top=max(101,120-cut),right=bx+140,bottom=180-cut,
               center_x=bx+70,center_y=max(110,150-cut),confidence=.99),
          dict(text='完整新消息',left=bx,top=248,right=bx+140,bottom=268,center_x=bx+70,center_y=258,confidence=.99)]
    messages=s.parse_messages_from_ocr(rows,image.size,target='CJTEST01',screenshot=image,layout_snapshot=layout)
    assert [m['content'] for m in messages]==['完整新消息']


def test_synthetic_missing_chat_separator_fails_closed():
    width,height=784,844
    image=Image.new('RGB',(width,height),(250,250,250));d=ImageDraw.Draw(image)
    d.rectangle((0,0,59,height-1),fill=(225,225,225))
    d.rectangle((60,0,391,height-1),fill=(235,235,235))
    d.line((392,667,width-1,667),fill=(190,190,190),width=1)
    ocr=[dict(text='搜索',left=75,top=45,right=129,bottom=69,center_x=102,center_y=57,confidence=.99)]
    result=s.win32_ocr_layout.build_structural_layout_regions(image,ocr_items=ocr,search_anchor_items=ocr)
    assert not result['ok'] and 'chat_header_boundary_missing' in result['conflicts'],result


def test_synthetic_separator_thickness_and_nearby_bubble():
    for thickness in (1,2,3,4,6):
        image=Image.new('RGB',(500,250),(250,250,250));d=ImageDraw.Draw(image)
        d.rectangle((0,80,499,80+thickness-1),fill=(200,200,200))
        d.rectangle((100,93,390,170),fill=(120,220,90))
        y=s.win32_ocr_layout._separator_content_start(image,left=0,right=500,edge_y=79,measured_row_height=24)
        assert y==80+thickness


def test_partial_prefix_does_not_hide_invalid_row_geometry():
    from test_frame_avatars import synthetic_frame,draw_avatar
    image,layout=synthetic_frame();draw_avatar(image,930,82)
    assert s.frame_avatars.avatar_table(image,layout)['top_fragments']
    for bounds in ([],[10,20],[10,float('nan'),30,40],[10,20,10,40],[10,'invalid',30,40]):
        with pytest.raises(s.frame_avatars.AvatarEvidenceError):
            s.message_row_avatar_role_details(image,bounds,image.size,layout_snapshot=layout)
