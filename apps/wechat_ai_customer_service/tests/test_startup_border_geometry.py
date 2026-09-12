"""Geometry checks shared with the downstream original-frame replay suite."""
import pytest
from PIL import Image,ImageDraw
from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as s

@pytest.mark.parametrize('scale',[1,1.25,1.5,2])
@pytest.mark.parametrize('width',[600,1000])
@pytest.mark.parametrize('thickness',[1,3])
def test_separator_exit_ignores_partial_bubble(scale,width,thickness):
    width=round(width*scale);height=round(400*scale);edge=round(80*scale)
    line_height=max(1,round(thickness*scale))
    image=Image.new('RGB',(width,height),(250,250,250));d=ImageDraw.Draw(image)
    d.rectangle((0,edge,width-1,edge+line_height-1),fill=(240,240,240))
    d.rectangle((round(width*.15),edge+line_height,round(width*.40),edge+round(35*scale)),fill=(238,238,240))
    actual=s.win32_ocr_layout._separator_content_start(image,left=0,right=width,edge_y=edge-1,measured_row_height=round(24*scale))
    assert actual==edge+line_height

@pytest.mark.parametrize('scale',[1,1.5,2])
@pytest.mark.parametrize('attached',[False,True])
def test_border_exclusion_requires_no_inward_attachment(scale,attached):
    size=(round(600*scale),round(500*scale))
    image=Image.new('RGB',size,(250,250,250));d=ImageDraw.Draw(image)
    left,top,right,bottom=[round(v*scale) for v in (100,80,600,420)]
    stroke=max(1,round(2*scale))
    d.rectangle((left,top,right-1,top+stroke-1),fill=(220,220,220))
    d.rectangle((right-stroke,top,right-1,bottom-1),fill=(220,220,220))
    box=[round(v*scale) for v in (546,180,580,214)]
    d.rectangle(box,fill=(60,90,120))
    if attached:d.rectangle((box[2],box[1]+stroke,right-1,box[1]+2*stroke),fill=(60,90,120))
    layout={'valid':True,'dpi_scale':scale,'message_viewport_bounds':[left,top,right,bottom]}
    table=s.frame_avatars.avatar_table(image,layout)
    borders=[x for x in table['excluded'] if x['reason']=='viewport_connected_border']
    assert bool(borders) is not attached
    if attached:assert table['unresolved'],table
    else:assert len(table['components'])==1 and not table['unresolved']
