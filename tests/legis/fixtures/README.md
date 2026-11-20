`detail_synthetic.json` is made up. It follows the field names in the General
Assembly web service's WSDL and in the Open States Georgia scraper, so the
parser can be tested before the first live run. The first run on GitHub
Actions saves real responses here (`detail_<id>.json`) and the tests switch to them.
