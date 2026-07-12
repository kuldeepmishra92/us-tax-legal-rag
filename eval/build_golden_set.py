#!/usr/bin/env python3
"""
build_golden_set.py — assembles the hand-authored golden set into eval/golden_set.csv.

Every row's ground_truth_answer was verified by an agent/human directly against
the actual extracted chunk text (and, for ambiguous cases, the raw source PDF)
before being added here — not generated from general knowledge. See ROWS below
for the full list; each entry traces to a specific document + page.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROWS = []

def add(query, answer, doc, category, page, difficulty):
    ROWS.append({
        "sample_query": query,
        "ground_truth_answer": answer,
        "source_document": doc,
        "category": category,
        "page_reference": page,
        "difficulty": difficulty,
    })

# ============================== TAX (25) ==============================
PUB502 = "IRS Publication 502 — Medical and Dental Expenses"
PUB505 = "IRS Publication 505 — Tax Withholding and Estimated Tax"
PUB334 = "IRS Publication 334 — Tax Guide for Small Business"
PUB526 = "IRS Publication 526 — Charitable Contributions"
PUB503 = "IRS Publication 503 — Child and Dependent Care Expenses"
PUB514 = "IRS Publication 514 — Foreign Tax Credit for Individuals"
PUB517 = "IRS Publication 517 — Social Security for Members of the Clergy"
PUB523 = "IRS Publication 523 — Selling Your Home"
PUB501 = "IRS Publication 501 — Dependents, Standard Deduction, and Filing Information"
PUB525 = "IRS Publication 525 — Taxable and Nontaxable Income"

add("Can a taxpayer deduct the cost of maternity clothes as a medical expense?",
    "No — you can't include amounts you pay for maternity clothes as medical expenses.",
    PUB502, "tax", "15", "easy")
add("What is the maximum nightly amount that can be included as a medical expense for lodging when a person travels for medical care?",
    "$100 per night (meals aren't included).",
    PUB502, "tax", "10", "easy")
add("According to IRS Publication 505, what income threshold triggers the 0.9% Additional Medicare Tax for a single filer?",
    "$200,000",
    PUB505, "tax", "23", "easy")
add("What is the Additional Medicare Tax income threshold for a married couple filing jointly, per IRS Publication 505?",
    "$250,000",
    PUB505, "tax", "23", "easy")
add("For 2026, at what taxable income level does the itemized-deduction reduction begin for a married couple filing jointly or a qualifying surviving spouse, per IRS Publication 505?",
    "$768,700",
    PUB505, "tax", "23", "medium")
add("What identification number must the IRS issue to a nonresident or resident alien who is not eligible for a Social Security Number, per IRS Publication 334?",
    "An Individual Taxpayer Identification Number (ITIN).",
    PUB334, "tax", "6", "easy")
add("Under the simplified method for the home office deduction described in IRS Publication 334, what is the dollar rate per square foot and the maximum square footage allowed?",
    "$5 per square foot, for up to 300 square feet.",
    PUB334, "tax", "41-42", "medium")
add("According to IRS Publication 334, if a taxpayer's gross nonfarm income is $10,860 or less, what are their net earnings for self-employment tax purposes?",
    "Two-thirds of their gross nonfarm income.",
    PUB334, "tax", "46", "easy")
add("According to IRS Publication 334, what are the net earnings for self-employment tax purposes if a taxpayer's gross nonfarm income is more than $10,860?",
    "$7,840",
    PUB334, "tax", "46", "easy")
add("Per IRS Publication 526, can a volunteer deduct the value of their own time or services donated to a qualified organization?",
    "No — you can't deduct the value of your time or services.",
    PUB526, "tax", "7", "easy")
add("According to IRS Publication 526, what standard mileage rate can a volunteer deduct per mile for driving related to volunteer work, if they don't want to calculate actual car expenses?",
    "14 cents per mile.",
    PUB526, "tax", "7", "easy")
add("Per IRS Publication 526, under what condition can a taxpayer deduct a donation of clothing or a household item that is not in good used condition or better?",
    "Only if they deduct more than $500 for the item and include a qualified appraisal prepared by a qualified appraiser along with a completed Form 8283, Section B.",
    PUB526, "tax", "11", "medium")
add("How does IRS Publication 503 determine the custodial parent for child and dependent care purposes when a child spends an equal number of nights with each parent?",
    "The custodial parent is the parent with the higher adjusted gross income.",
    PUB503, "tax", "3-4", "medium")
add("According to IRS Publication 503, are meals provided to a housekeeper in the taxpayer's home, because of the housekeeper's employment, counted as work-related expenses?",
    "Yes, they count as work-related expenses.",
    PUB503, "tax", "8", "easy")
add("In the Form 2441 Part III worksheet example in IRS Publication 503, how much in qualified expenses did James Paris (a disabled qualifying person over age 12) incur and pay in 2025?",
    "$18,500",
    PUB503, "tax", "13", "medium")
add("Per IRS Publication 514, can a bona fide resident of Puerto Rico for the entire tax year claim the U.S. foreign tax credit under the same general rules as U.S. citizens?",
    "Yes.",
    PUB514, "tax", "9", "easy")
add("According to IRS Publication 517, within what time period must a claim for refund of overpaid self-employment (SE) tax generally be filed on Form 1040-X?",
    "Within 3 years from the date the return was filed, or within 2 years from the date the tax was paid, whichever is later.",
    PUB517, "tax", "6-7", "medium")
add("Per IRS Publication 517, on which form does a member of the clergy deduct ministerial expenses incurred while performing marriages and baptisms, and where is the net amount carried to?",
    "Deducted on Schedule C (Form 1040), with the net amount carried to line 2 of Schedule SE (Form 1040).",
    PUB517, "tax", "8", "medium")
add("In the home-sale example in IRS Publication 523, how much unrecaptured section 1250 gain (from post-May 6, 1997 depreciation) does Taylor have to account for when selling the rental property?",
    "$27,000",
    PUB523, "tax", "17-18", "hard")
add("Per IRS Publication 523, what Internal Revenue Code section prevents like-kind exchange replacement property from being immediately converted into a main home?",
    "Section 1031(a)(1).",
    PUB523, "tax", "6", "medium")
add("According to the Standard Deduction Chart in IRS Publication 501, what is the 2025 standard deduction for a taxpayer filing as head of household?",
    "$23,625",
    PUB501, "tax", "25", "easy")
add("According to the Standard Deduction Chart in IRS Publication 501, what is the 2025 standard deduction for a single filer or a taxpayer married filing separately?",
    "$15,750",
    PUB501, "tax", "25", "easy")
add("What is the 2025 dollar limitation under section 125(i) on voluntary employee salary reductions for contributions to health FSAs, per IRS Publication 525?",
    "$3,300",
    PUB525, "tax", "1", "easy")
add("According to IRS Publication 525, are qualified wildfire relief payments taxable?",
    "No, they are not taxable.",
    PUB525, "tax", "1", "easy")
add("Per IRS Publication 525, name two of the four circumstances under which the entire cost of employer-provided group-term life insurance is excluded from an employee's income.",
    "Any two of: (1) the employee is permanently and totally disabled and has ended employment; (2) the employer is the sole beneficiary of the policy for the entire period the insurance is in force; (3) a charitable organization eligible for deductible contributions is the sole beneficiary for the entire period; (4) the plan existed on January 1, 1984, and the employee either retired before January 2, 1984 while covered, or reached age 55 before January 2, 1984 and was employed by the employer/predecessor in 1983.",
    PUB525, "tax", "7", "hard")

# ============================== JUDGMENTS (25) ==============================
DEVAS = "DEVAS (MAURITIUS) LTD. et al v. ANTRIX CORP. LTD. et al"
MCLAUGHLIN = "McLAUGHLIN CHIROPRACTIC ASSOCIATES, INC v. McKESSON CORP. et al"
MARTIN = "MARTIN, individually and as parent and next friend of G. W., a minor, et al v. UNITED STATES et al"
STANLEY = "STANLEY v. CITY OF SANFORD, FLORIDA"
FELICIANO = "FELICIANO v. DEPARTMENT OF TRANSPORTATION"
NRC = "NUCLEAR REGULATORY COMMISSION et al v. TEXAS et al"
HEWITT = "HEWITT v. UNITED STATES"
RIVERS = "RIVERS v. GUERRERO, DIRECTOR, TEXAS DEPARTMENT OF CRIMINAL JUSTICE, CORRECTIONAL INSTITUTIONS DIVISION"
FULD = "FULD et al v. PALESTINE LIBERATION ORGANIZATION et al"
ZUCH = "COMMISSIONER OF INTERNAL REVENUE v. ZUCH"
PARRISH = "PARRISH v. UNITED STATES"
SMITHWESSON = "SMITH & WESSON BRANDS, INC., et al v. ESTADOS UNIDOS MEXICANOS"
RJREYNOLDS = "FOOD AND DRUG ADMINISTRATION et al v. R. J. REYNOLDS VAPOR CO. et al"
CALUMET = "ENVIRONMENTAL PROTECTION AGENCY v. CALUMET SHREVEPORT REFINING, L.L.C., et al"

add("In Devas (Mauritius) Ltd. v. Antrix Corp. Ltd., what did the Supreme Court hold regarding personal jurisdiction under the Foreign Sovereign Immunities Act (FSIA)?",
    "Personal jurisdiction exists under the FSIA when an immunity exception applies and service is proper.",
    DEVAS, "judgments", "2-3", "easy")
add("In Devas v. Antrix, which court of appeals' decision was under review, and on what basis did that court find personal jurisdiction lacking?",
    "The Ninth Circuit's decision; it held that, bound by Circuit precedent, the FSIA also requires a traditional minimum-contacts analysis, and Antrix lacked sufficient suit-related contacts with the United States.",
    DEVAS, "judgments", "2-3", "medium")
add("What dollar amount did the arbitral panel award Devas in damages (plus interest) in its dispute with Antrix Corporation?",
    "$562.5 million",
    DEVAS, "judgments", "2-3", "easy")
add("Who delivered the opinion of the Court in McLaughlin Chiropractic Associates, Inc. v. McKesson Corp.?",
    "Justice Kavanaugh",
    MCLAUGHLIN, "judgments", "8-9", "easy")
add("In McLaughlin Chiropractic Associates v. McKesson Corp., the Court uses 'enforcement proceedings' as shorthand for what phrase used in the Administrative Procedure Act, and where is that phrase codified?",
    "'Civil or criminal proceedings for judicial enforcement,' codified at 5 U.S.C. §703.",
    MCLAUGHLIN, "judgments", "8-9", "medium")
add("Who delivered the opinion of the Court in the Martin v. United States case concerning the FBI's mistaken raid on G. W.'s family home?",
    "Justice Gorsuch",
    MARTIN, "judgments", "25-26", "easy")
add("Under Gaubert, what two elements must an official's actions satisfy for the discretionary-function exception to the Federal Tort Claims Act to apply, as discussed in Martin v. United States?",
    "The official's actions must (1) involve an element of judgment, and (2) be based on considerations of public policy.",
    MARTIN, "judgments", "25-26", "hard")
add("Which Justice wrote the concurrence in part in Stanley v. City of Sanford, Florida, arguing that a retiree who earned benefits while a qualified individual is covered by ADA Title I's protections?",
    "Justice Sotomayor",
    STANLEY, "judgments", "52-53", "easy")
add("In Feliciano v. Department of Transportation, under what statutory provision did the dissent conclude Feliciano would have been entitled to differential pay?",
    "Section 101(a)(13)(B).",
    FELICIANO, "judgments", "35-37", "medium")
add("Which Justice wrote the dissenting opinion in Feliciano v. Department of Transportation?",
    "Justice Thomas",
    FELICIANO, "judgments", "35-37", "easy")
add("In the dissent in Nuclear Regulatory Commission v. Texas, what 'familiar' rule of statutory construction is invoked to argue that the Nuclear Waste Policy Act (NWPA) controls over the NRC's general licensing authority?",
    "The rule that 'a specific statute controls over a general one.'",
    NRC, "judgments", "39-40", "medium")
add("In Hewitt v. United States, which grammatical tense of the phrase 'has . . . been imposed' in § 403(b) of the First Step Act did the Court find significant to its interpretation?",
    "The present-perfect tense, as opposed to the past-perfect tense.",
    HEWITT, "judgments", "10", "medium")
add("Who delivered the opinion of the Court in Rivers v. Guerrero, concerning AEDPA's rules for second-or-successive habeas petitions?",
    "Justice Jackson",
    RIVERS, "judgments", "8-9", "easy")
add("Under what federal statute were the underlying civil-damages lawsuits filed in Fuld v. Palestine Liberation Organization?",
    "The Antiterrorism Act of 1990 (ATA).",
    FULD, "judgments", "2-3", "easy")
add("In Fuld v. Palestine Liberation Organization, what constitutional provision did the PSJVTA's personal-jurisdiction consent provisions allegedly violate?",
    "The Due Process Clause of the Fifth Amendment.",
    FULD, "judgments", "2-3", "easy")
add("In Commissioner of Internal Revenue v. Zuch, what dollar amount in estimated tax payments was in dispute over allocation between Zuch and her ex-husband?",
    "$50,000",
    ZUCH, "judgments", "8-9", "easy")
add("In Commissioner of Internal Revenue v. Zuch, which two Circuits did the Third Circuit acknowledge it was 'parting ways' with regarding Tax Court jurisdiction over collection due process proceedings once there is no longer an underlying levy?",
    "The Fourth Circuit and the D.C. Circuit.",
    ZUCH, "judgments", "8-9", "hard")
add("In Parrish v. United States, under what section of Title 28 may a district court reopen the time to file a notice of appeal?",
    "Section 2107(c).",
    PARRISH, "judgments", "17-18", "easy")
add("Per 28 U.S.C. § 2107(c), as discussed in Parrish v. United States, how many days from the date of entry of the reopening order does a district court have to reopen the time for appeal?",
    "14 days.",
    PARRISH, "judgments", "17-18", "easy")
add("What federal statute does Mexico's tort-liability theory against U.S. gun manufacturers run into in Smith & Wesson Brands, Inc. v. Estados Unidos Mexicanos, generally barring such claims?",
    "The Protection of Lawful Commerce in Arms Act (PLCAA).",
    SMITHWESSON, "judgments", "9-10", "medium")
add("According to Smith & Wesson Brands, Inc. v. Estados Unidos Mexicanos, what percentage of guns recovered at crime scenes in Mexico did the Mexican government say originated in the United States?",
    "As many as 90%.",
    SMITHWESSON, "judgments", "9-10", "easy")
add("Which Justice dissented from the Court's interpretation of § 387l(a)(1) in FDA v. R. J. Reynolds Vapor Co., regarding retailers' ability to challenge FDA denial orders?",
    "Justice Jackson",
    RJREYNOLDS, "judgments", "15-16", "easy")
add("In FDA v. R. J. Reynolds Vapor Co., what interpretive canon states that when Congress uses a different term in another part of a statute, the presumption is that the different term denotes a different idea?",
    "The canon that 'a material variation in terms suggests a variation in meaning' — described by the Court via Scalia & Garner's Reading Law as the presumption that a different term denotes a different idea.",
    RJREYNOLDS, "judgments", "15-16", "hard")
add("In EPA v. Calumet Shreveport Refining, L.L.C., what Clean Air Act program requiring refineries to blend ethanol and other renewable fuels was at issue?",
    "The renewable fuel program (RFP).",
    CALUMET, "judgments", "7-8", "easy")
add("Per EPA v. Calumet Shreveport Refining, L.L.C., what credit system do covered refineries use to demonstrate compliance with their renewable-fuel-blending obligations?",
    "Renewable Identification Number (RIN) credits.",
    CALUMET, "judgments", "7-8", "medium")

# ============================== ACTS (25) ==============================
POSTAL = "Postal Service Reform Act of 2022"
TAXPAYERFIRST = "Taxpayer First Act"
SBIR = "SBIR and STTR Extension Act of 2022"
GOODSAMARITAN = "Good Samaritan Remediation of Abandoned Hardrock Mines Act of 2024"
OLYMPIC = "Empowering Olympic, Paralympic, and Amateur Athletes Act of 2020"
FIREGRANTS = "Fire Grants and Safety Act of 2023"
OCEANSHIPPING = "Ocean Shipping Reform Act of 2022"
SAVEOURSEAS = "Save Our Seas 2.0 Act"
AFGHANISTAN = "Extending Government Funding and Delivering Emergency Assistance Act"
HANNON = "Commander John Scott Hannon Veterans Mental Health Care Improvement Act of 2019"
SUPPORTINGAMERICA = "Supporting America’s Children and Families Act"
VETAUTO = "Veterans Auto and Education Improvement Act of 2022"
VETCOMPACT = "Veterans Comprehensive Prevention, Access to Care, and Treatment Act of 2020"
SAFEGUARDTRIBAL = "Safeguard Tribal Objects of Patrimony Act of 2021"
CONTAPPROP2020 = "Continuing Appropriations Act, 2020, and Health Extenders Act of 2019"
AMERICANRELIEF = "American Relief Act, 2025"
FISA = "Reforming Intelligence and Securing America Act"
NATLHERITAGE = "National Heritage Area Act"

add("Under the Postal Service Reform Act of 2022, during what 6-month period could eligible Postal Service annuitants elect special enrollment in Medicare Part B?",
    "The 6-month period beginning on April 1, 2024.",
    POSTAL, "acts", "10", "medium")
add("Under SEC. 1206 of the Taxpayer First Act (Reform of Notice of Contact of Third Parties), what does the effective-date clause say about when the amendment applies?",
    "The amendment applies to notices provided, and contacts of persons made, after the date which is 45 days after the date of the enactment of this Act.",
    TAXPAYERFIRST, "acts", "10-11", "medium")
add("Under SEC. 8 of the SBIR and STTR Extension Act of 2022, what happens to a small business concern's minimum performance standard if it received more than 50 Phase I awards during a covered period?",
    "Each minimum performance standard established under the Act is doubled for that covered period.",
    SBIR, "acts", "11-12", "medium")
add("Per the Good Samaritan Remediation of Abandoned Hardrock Mines Act of 2024, who is defined as the 'Administrator' under the Act?",
    "The Administrator of the Environmental Protection Agency.",
    GOODSAMARITAN, "acts", "3", "easy")
add("Under SEC. 9 of the Empowering Olympic, Paralympic, and Amateur Athletes Act of 2020, what kinds of actions are exempted from the automatic stay in bankruptcy cases?",
    "Actions by an amateur sports organization to replace a national governing body, or by the corporation to revoke the certification of a national governing body, both as defined under title 36, United States Code.",
    OLYMPIC, "acts", "28", "hard")
add("Under SEC. 506 of the Fire Grants and Safety Act of 2023, how many days after enactment must the Commission submit a report on facilitating environmental reviews of nuclear reactor license applications?",
    "180 days.",
    FIREGRANTS, "acts", "32", "easy")
add("According to SEC. 4 of the Ocean Shipping Reform Act of 2022, which federal agency must a person register a shipping exchange with?",
    "The Federal Maritime Commission.",
    OCEANSHIPPING, "acts", "2-3", "easy")
add("Under the Ocean Shipping Reform Act of 2022's shipping exchange registry provision, how many years after enactment must the Federal Maritime Commission issue implementing regulations?",
    "Not later than 3 years after the date of enactment.",
    OCEANSHIPPING, "acts", "2-3", "medium")
add("Per SEC. 122 of the Save Our Seas 2.0 Act, what is the name of the prize competition established to encourage innovation that reduces plastic waste and marine debris?",
    "The 'Genius Prize for Save Our Seas Innovations.'",
    SAVEOURSEAS, "acts", "11", "easy")
add("How often does the Save Our Seas 2.0 Act's Genius Prize competition award one or more prizes to qualifying projects?",
    "Biennially.",
    SAVEOURSEAS, "acts", "11", "easy")
add("Under SEC. 2507 of the Extending Government Funding and Delivering Emergency Assistance Act, what short title is given to that division of the Act?",
    "The 'Afghanistan Supplemental Appropriations Act, 2022.'",
    AFGHANISTAN, "acts", "37", "medium")
add("Per SEC. 505 of the Commander John Scott Hannon Veterans Mental Health Care Improvement Act of 2019, how many days after enactment must the Secretary of Veterans Affairs conduct the survey on alternative work schedule attitudes among eligible veterans?",
    "180 days.",
    HANNON, "acts", "44", "easy")
add("Under that same SEC. 505 provision of the Commander John Scott Hannon Veterans Mental Health Care Improvement Act of 2019, how many days after enactment must the Secretary brief the Senate and House Committees on Veterans' Affairs?",
    "270 days.",
    HANNON, "acts", "44", "easy")
add("Under SEC. 107 of the Supporting America's Children and Families Act, what percentage of appropriated funds must the Secretary reserve for grants to Indian tribes and tribal organizations?",
    "3 percent.",
    SUPPORTINGAMERICA, "acts", "7-8", "medium")
add("Per SEC. 11 of the Veterans Auto and Education Improvement Act of 2022, how many uniform applications must the Secretary maintain in total for institutions seeking course-of-education approval?",
    "Two: one uniform application for institutions of higher learning, and one for other educational institutions and training establishments.",
    VETAUTO, "acts", "12", "medium")
add("Under SEC. 11's requirements in the Veterans Auto and Education Improvement Act of 2022, what percentage of an institution's Title IV Higher Education Act funding must an adverse-action fine or penalty equal or exceed to disqualify it from the uniform application attestation?",
    "Five percent (5%).",
    VETAUTO, "acts", "12", "hard")
add("Per the Veterans Comprehensive Prevention, Access to Care, and Treatment Act of 2020's short-title section, what is the Act's short-form nickname?",
    "The 'Veterans COMPACT Act of 2020.'",
    VETCOMPACT, "acts", "2", "easy")
add("Under SEC. 5 of the Safeguard Tribal Objects of Patrimony Act of 2021, within how many days after delivery must the Secretary determine whether an Item Requiring Export Certification is an Item Prohibited from Exportation?",
    "60 days.",
    SAFEGUARDTRIBAL, "acts", "9-10", "medium")
add("Per SEC. 5 of the Safeguard Tribal Objects of Patrimony Act of 2021, under which two federal laws may a forfeited, prohibited item be repatriated to the appropriate Indian Tribe or Native Hawaiian organization?",
    "The Native American Graves Protection and Repatriation Act, or the Archaeological Resources Protection Act of 1979.",
    SAFEGUARDTRIBAL, "acts", "9-10", "hard")
add("Under SEC. 136(a) of the Continuing Appropriations Act, 2020, and Health Extenders Act of 2019, what additional rate-of-operations amount is provided for 'Indian Health Service—Indian Health Services'?",
    "$18,397,500.",
    CONTAPPROP2020, "acts", "8-9", "easy")
add("Under SEC. 136(b) of the same Act, what additional rate-of-operations amount is provided for 'Indian Health Service—Indian Health Facilities'?",
    "$631,000.",
    CONTAPPROP2020, "acts", "8-9", "easy")
add("Under TITLE X of the American Relief Act, 2025, how much additional funding is provided for 'Construction, Minor Projects' related to Hurricanes Milton and Helene, and until what date does it remain available?",
    "$2,020,000, remaining available until September 30, 2029.",
    AMERICANRELIEF, "acts", "37", "medium")
add("Per SEC. 13 of the Reforming Intelligence and Securing America Act, what is the maximum prison term for a person guilty of the unauthorized-disclosure offense amended into section 109 of FISA?",
    "Not more than 10 years.",
    FISA, "acts", "21-22", "medium")
add("Under SEC. 3 of the National Heritage Area Act, what is the proposed name for the National Heritage Area study covering all or a portion of Honolulu County on the island of Oahu?",
    "The 'Kaena Point National Heritage Area.'",
    NATLHERITAGE, "acts", "7", "easy")
add("Per SEC. 3 of the National Heritage Area Act, what is the proposed name for the National Heritage Area study covering areas in the states of Virginia and North Carolina?",
    "The 'Great Dismal Swamp National Heritage Area.'",
    NATLHERITAGE, "acts", "7", "easy")

# ============================== POV (25) ==============================
SBCONTRACTING = "An Overview of Small Business Contracting"
SBA8A = "SBA’s 8(a) Business Development Program: Structure and Current Issues"
PREEMPTION = "Federal Preemption and State Authority to Deter the Presence of Unlawfully Present Aliens: An Overview and Issues for the 119th Congress"
NATLINJUNCTIONS100 = "Nationwide Injunctions in the First Hundred Days of the Second Trump Administration"
VACANCIESACT = "The Vacancies Act: A Legal Overview"
TRIBALFORESTRY = "Introduction to Tribal Forestry"
GRANTSPRIMER = "Federal Grants-in-Aid Administration: A Primer"
OIRA = "The Office of Information and Regulatory Affairs (OIRA): Overview and Major Responsibilities"
FEDSTATSTERRITORIES = "Federal Statistical Data for U.S. Territories: Issues and Resources"
ARTICLEII = "Congress and the Scope of the President’s Article II Foreign Policy Authorities"
CONTAPPROP2026 = "Overview of Continuing Appropriations for FY2026 (Division A of P.L. 119-37)"
OFFSHOREWIND = "Offshore Wind Energy Development: Legal Framework"
MARRIAGEPENALTY = "Marriage Penalties and Bonuses in the Federal Tax Code"
VOTERELIGIBILITY = "Federal Voter Eligibility and Voter Registration: Overview and Issues for Congress"
PFAS = "Examining the Future of PFAS Cleanup and Disposal Policy"

add("Under the SBA size-protest process described in 'An Overview of Small Business Contracting,' how many business days does the SBA's Area Office generally have to determine an offeror's size status after receiving a protest?",
    "15 business days.",
    SBCONTRACTING, "pov", "34", "easy")
add("Per 'SBA's 8(a) Business Development Program,' what net worth and average adjusted gross income thresholds must an individual meet to be considered 'economically disadvantaged' for 8(a) program purposes?",
    "A net worth of less than $850,000, and an adjusted gross income averaged over the three preceding years of $400,000 or less.",
    SBA8A, "pov", "5-6", "medium")
add("According to 'SBA's 8(a) Business Development Program,' which federal district court case led the SBA to stop presuming social disadvantage based on ethnic or racial group membership?",
    "Ultima Servs. Corp. v. U.S. Department of Agriculture (a July 2023 ruling).",
    SBA8A, "pov", "5-6", "medium")
add("Per 'Federal Preemption and State Authority to Deter the Presence of Unlawfully Present Aliens,' which federal circuit court did the appeal of Oklahoma's H.B. 4156 case (United States v. Oklahoma) go to?",
    "The Tenth Circuit.",
    PREEMPTION, "pov", "27", "easy")
add("According to the same CRS report on Oklahoma's H.B. 4156, on what date did the Tenth Circuit vacate oral arguments and dismiss the appeal as moot?",
    "March 25, 2025.",
    PREEMPTION, "pov", "27", "medium")
add("Per 'Nationwide Injunctions in the First Hundred Days of the Second Trump Administration,' how many nationwide injunctions did the report identify as issued between January 20 and April 29, 2025?",
    "25",
    NATLINJUNCTIONS100, "pov", "4-5", "easy")
add("According to the same report, how many nationwide injunction cases did a March 2025 CRS report identify from the first Trump Administration, and how many from the Biden Administration?",
    "86 from the first Trump Administration, and 28 from the Biden Administration.",
    NATLINJUNCTIONS100, "pov", "4-5", "medium")
add("Per 'The Vacancies Act: A Legal Overview,' which clause of the U.S. Constitution generally requires 'Officers of the United States' to be appointed through nomination by the President with the advice and consent of the Senate?",
    "The Appointments Clause (U.S. Const. art. II, § 2, cl. 2).",
    VACANCIESACT, "pov", "3-4", "easy")
add("According to 'The Vacancies Act: A Legal Overview,' have the courts that have considered the President's claimed inherent authority to appoint acting officers accepted or rejected that claim?",
    "Rejected — the courts to consider the merits of the claim have rejected the idea that this inherent authority exists (though appeals were ongoing).",
    VACANCIESACT, "pov", "3-4", "medium")
add("Per 'Introduction to Tribal Forestry,' which federal agency holds tribal trust lands in trust on behalf of a Tribe or tribal citizen?",
    "The Bureau of Indian Affairs (BIA).",
    TRIBALFORESTRY, "pov", "4", "easy")
add("According to 'Introduction to Tribal Forestry,' what distinguishes 'restricted fee lands' from ordinary fee (private property) lands owned by a Tribe or tribal citizen?",
    "Restricted fee lands may not be alienated or encumbered (sold, gifted, or leased) without federal approval, unlike ordinary fee lands.",
    TRIBALFORESTRY, "pov", "4", "medium")
add("Per 'Federal Grants-in-Aid Administration: A Primer,' what two characteristics are commonly used to describe or classify federal grants?",
    "How broadly grant funds may be used, and the method of distribution.",
    GRANTSPRIMER, "pov", "7-8", "easy")
add("According to 'The Office of Information and Regulatory Affairs (OIRA): Overview and Major Responsibilities,' into how many branches was OIRA organized as of 2023, and what were they?",
    "Six branches: (1) information policy, (2) statistical and science policy, (3) natural resources and environment, (4) food, health, and labor, (5) transportation and security, and (6) privacy.",
    OIRA, "pov", "9-10", "hard")
add("Per the same OIRA report, in what year was OIRA's privacy policy branch established?",
    "2016",
    OIRA, "pov", "9-10", "easy")
add("According to 'Federal Statistical Data for U.S. Territories,' what data source has the Census Bureau drawn on to help address nonresponse in the American Community Survey (ACS)?",
    "Administrative data from the Internal Revenue Service and other agencies.",
    FEDSTATSTERRITORIES, "pov", "15", "medium")
add("Per 'Federal Statistical Data for U.S. Territories,' name one territory that lacks a permanent unemployment insurance program, limiting available administrative employment data.",
    "American Samoa, the Commonwealth of the Northern Mariana Islands (CNMI), or Guam (any one is correct).",
    FEDSTATSTERRITORIES, "pov", "15", "easy")
add("Per 'Congress and the Scope of the President's Article II Foreign Policy Authorities,' according to the Zivotofsky framework, when is presidential authority on its 'firmest footing'?",
    "When Congress has authorized the action.",
    ARTICLEII, "pov", "2", "easy")
add("According to the same CRS report, in Dames & Moore v. Regan, what type of authority did the Supreme Court hold the President has to enter into certain executive agreements?",
    "Independent Article II authority.",
    ARTICLEII, "pov", "2", "medium")
add("Per 'Overview of Continuing Appropriations for FY2026,' by what date must federal agencies confirm to OPM that they issued notices rescinding RIFs noticed between October 1 and November 12, 2025?",
    "No later than November 19, 2025.",
    CONTAPPROP2026, "pov", "12", "medium")
add("According to the same report on FY2026 continuing appropriations, until what date does the Act limit agencies' use of reductions in force (RIFs) to reduce the federal workforce?",
    "January 30, 2026.",
    CONTAPPROP2026, "pov", "12", "easy")
add("Per 'Offshore Wind Energy Development: Legal Framework,' which federal agency receives proposals for offshore wind and related infrastructure projects?",
    "The Bureau of Ocean Energy Management (BOEM).",
    OFFSHOREWIND, "pov", "4", "easy")
add("According to 'Marriage Penalties and Bonuses in the Federal Tax Code,' how did married women's participation elasticities with respect to their own wages change from 1980 to 2000, per Blau and Kahn's estimates?",
    "They fell from a range of 0.53-0.61 in 1980 to a range of 0.27-0.30 in 2000.",
    MARRIAGEPENALTY, "pov", "25", "hard")
add("Per 'Federal Voter Eligibility and Voter Registration,' what does NVRA generally prohibit state election officials from doing to individuals on the federal voter registration list?",
    "NVRA prohibits state election officials from removing an individual from the voter registration list for federal elections except for certain, stated reasons.",
    VOTERELIGIBILITY, "pov", "17", "medium")
add("According to the same report on Federal Voter Eligibility and Voter Registration, which bill introduced in the 119th Congress would clarify state election officials' authority to remove noncitizens from voter registration databases?",
    "The SAVE Act (H.R. 22/S. 128).",
    VOTERELIGIBILITY, "pov", "17", "easy")
add("Per 'Examining the Future of PFAS Cleanup and Disposal Policy,' what is the term for the protection a settling potentially responsible party (PRP) receives from future contribution claims related to a matter addressed in its settlement?",
    "Contribution protection.",
    PFAS, "pov", "16", "easy")

def main():
    with open(ROOT / "eval" / "golden_set.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["sample_query", "ground_truth_answer", "source_document",
                                           "category", "page_reference", "difficulty"])
        w.writeheader()
        w.writerows(ROWS)
    print(f"wrote {len(ROWS)} rows to eval/golden_set.csv")

if __name__ == "__main__":
    main()
