"""Georgia's 12 regional commissions and their member counties.

Source: Georgia Department of Audits and Accounts, Performance Audit Report
No. 19-11, "Regional Commissions" (November 2019), Appendix C, Survey
Response Rates, which lists every county in each region (respondents and
non-respondents together). Consolidated governments are listed there by
their consolidated name (Augusta-Richmond, Macon-Bibb and so on); here each
is filed under its county. https://open.ga.gov/openga/report/downloadFile?rid=22936
"""

from __future__ import annotations

SOURCE = ("Georgia Department of Audits and Accounts, Performance Audit Report No. 19-11, "
          "Regional Commissions (November 2019), Appendix C")
SOURCE_URL = "https://open.ga.gov/openga/report/downloadFile?rid=22936"

REGIONS: dict[str, list[str]] = {
    "Atlanta": ["Cherokee", "Douglas", "Fayette", "Gwinnett", "Henry", "Rockdale",
                "Clayton", "Cobb", "DeKalb", "Fulton"],
    "Central Savannah River Area": ["Columbia", "Glascock", "Hancock", "Jenkins", "Lincoln",
                                    "Taliaferro", "Warren", "Washington", "Richmond", "Burke",
                                    "Jefferson", "McDuffie", "Wilkes"],
    "Coastal": ["Bulloch", "Camden", "Effingham", "Liberty", "Long", "McIntosh",
                "Bryan", "Chatham", "Glynn", "Screven"],
    "Georgia Mountains": ["Banks", "Dawson", "Franklin", "Habersham", "Hall", "Lumpkin",
                          "Rabun", "Stephens", "Towns", "Union", "Forsyth", "Hart", "White"],
    "Heart of Georgia Altamaha": ["Candler", "Evans", "Jeff Davis", "Johnson", "Laurens",
                                  "Montgomery", "Tattnall", "Telfair", "Wayne", "Appling",
                                  "Bleckley", "Dodge", "Emanuel", "Toombs", "Treutlen",
                                  "Wheeler", "Wilcox"],
    "Middle Georgia": ["Baldwin", "Houston", "Monroe", "Peach", "Putnam", "Twiggs",
                       "Crawford", "Jones", "Bibb", "Pulaski", "Wilkinson"],
    "Northeast Georgia": ["Clarke", "Barrow", "Elbert", "Greene", "Jackson", "Jasper",
                          "Morgan", "Newton", "Oconee", "Oglethorpe", "Walton", "Madison"],
    "Northwest Georgia": ["Catoosa", "Dade", "Gilmer", "Gordon", "Murray", "Paulding",
                          "Pickens", "Whitfield", "Bartow", "Chattooga", "Fannin", "Floyd",
                          "Haralson", "Polk", "Walker"],
    "River Valley": ["Clay", "Muscogee", "Dooly", "Harris", "Macon", "Randolph", "Stewart",
                     "Sumter", "Talbot", "Webster", "Crisp", "Chattahoochee", "Quitman",
                     "Marion", "Schley", "Taylor"],
    "Southern Georgia": ["Bacon", "Ben Hill", "Berrien", "Brantley", "Brooks", "Clinch",
                         "Echols", "Irwin", "Pierce", "Tift", "Ware", "Atkinson", "Charlton",
                         "Coffee", "Cook", "Lanier", "Lowndes", "Turner"],
    "Southwest Georgia": ["Baker", "Calhoun", "Early", "Lee", "Mitchell", "Terrell", "Thomas",
                          "Colquitt", "Decatur", "Dougherty", "Grady", "Miller", "Seminole",
                          "Worth"],
    "Three Rivers": ["Butts", "Carroll", "Coweta", "Heard", "Lamar", "Meriwether", "Pike",
                     "Spalding", "Troup", "Upson"],
}

REGION_OF: dict[str, str] = {c: r for r, cs in REGIONS.items() for c in cs}
