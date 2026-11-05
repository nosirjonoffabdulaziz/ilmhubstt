import pytest

from app.services.transliteration_service import normalize_latin, to_latin


@pytest.mark.parametrize("src,expected", [
    ("Ўзбекистон", "O‘zbekiston"),
    ("ёз", "yoz"),
    ("Европа", "Yevropa"),
    ("поезд", "poyezd"),
    ("концерт", "konsert"),
    ("цирк", "sirk"),
    ("лицей", "litsey"),
    ("маъно", "ma’no"),
    ("Шаҳар", "Shahar"),
    ("ШАҲАР", "SHAHAR"),
    ("ғалаба", "g‘alaba"),
    ("қишлоқ", "qishloq"),
    ("ЎҚИТУВЧИ", "O‘QITUVCHI"),
    ("Салом, дўстим!", "Salom, do‘stim!"),
    ("Hello дунё 2025", "Hello dunyo 2025"),
    ("съезд", "s’yezd"),
    ("юлдуз", "yulduz"),
])
def test_uzbek(src, expected):
    assert to_latin(src, "uz") == expected


def test_uzbek_apostrophes_normalized():
    assert normalize_latin("o'zbek g`alaba ma'no O'ZBEK oʻqish", "uz") == "o‘zbek g‘alaba ma’no O‘ZBEK o‘qish"


def test_uzbek_latin_untouched_otherwise():
    assert to_latin("Bugun havo yaxshi.", "uz") == "Bugun havo yaxshi."


@pytest.mark.parametrize("src,expected", [
    ("Қазақстан", "Qazaqstan"),
    ("әке", "äke"),
    ("ұлы", "ūly"),
    ("Ине", "İne"),
    ("бір", "bır"),
    ("шаң", "şañ"),
    ("өнер", "öner"),
    ("үй", "üi"),
    ("Іле", "Ile"),
])
def test_kazakh(src, expected):
    assert to_latin(src, "kk") == expected


@pytest.mark.parametrize("src,expected", [
    ("Кыргызстан", "Kırgızstan"),
    ("өлкө", "ölkö"),
    ("үй", "üy"),
    ("жаңы", "jañı"),
    ("Европа", "Yevropa"),
    ("Ит", "İt"),
])
def test_kyrgyz(src, expected):
    assert to_latin(src, "ky") == expected


def test_other_language_apostrophes_kept():
    assert normalize_latin("don't", "kk") == "don't"
