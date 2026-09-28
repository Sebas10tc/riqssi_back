from app.services.video_analysis_service import video_label_from_index


def test_video_label_from_index_uses_fake_first_mapping():
    assert video_label_from_index(0) == "FAKE"
    assert video_label_from_index(1) == "REAL"
