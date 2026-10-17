from shop.billing import invoice


def test_positive_amount():
    assert invoice(10) == "Invoice: 10"
