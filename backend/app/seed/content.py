"""Static content the generator composes from — docs/12 §3.5.

Transcripts are template-composed rather than LLM-generated: generation has to be
offline, deterministic, and free at image-build time. The fragments are
channel-appropriate so a voice call does not read like an email.
"""

from __future__ import annotations

from typing import Final

from app.domain.enums import Category, FailureCode

#: A fixed team, so 640 interactions look like a contact centre rather than 640
#: strangers. Invented names, matching the synthetic corpus.
HANDLERS: Final[tuple[str, ...]] = (
    "A. Rahman",
    "B. Kaur",
    "C. Lim",
    "D. Fernandez",
    "E. Ng",
    "F. Abdullah",
    "G. Chandra",
    "H. Wong",
    "I. Prakash",
    "J. Teo",
    "K. Sathish",
    "L. Yusof",
)

GIVEN_NAMES: Final[tuple[str, ...]] = (
    "Aisha",
    "Bryan",
    "Charmaine",
    "Daniel",
    "Elaine",
    "Farhan",
    "Grace",
    "Hakim",
    "Irene",
    "Jason",
    "Karthik",
    "Lydia",
    "Marcus",
    "Nadia",
    "Oliver",
    "Priya",
    "Qiang",
    "Rachel",
    "Samuel",
    "Tanya",
    "Umar",
    "Vivian",
    "Wei Ming",
    "Xin Yi",
    "Yusuf",
    "Zoe",
    "Adeline",
    "Benedict",
    "Cheryl",
    "Dinesh",
    "Eunice",
    "Fabian",
    "Gwen",
    "Harith",
    "Ivy",
    "Joel",
    "Kelvin",
    "Lena",
    "Mervyn",
    "Natasha",
)

FAMILY_NAMES: Final[tuple[str, ...]] = (
    "Tan",
    "Lim",
    "Lee",
    "Ng",
    "Wong",
    "Chan",
    "Koh",
    "Goh",
    "Chua",
    "Yeo",
    "Sim",
    "Toh",
    "Ong",
    "Low",
    "Foo",
    "Kumar",
    "Rahman",
    "Ismail",
    "Nair",
    "Menon",
)

CITIES: Final[tuple[str, ...]] = (
    "Singapore",
    "Jurong East",
    "Tampines",
    "Woodlands",
    "Bedok",
    "Punggol",
    "Clementi",
    "Serangoon",
    "Yishun",
    "Bukit Batok",
)

STREETS: Final[tuple[str, ...]] = (
    "Ang Mo Kio Avenue",
    "Bukit Timah Road",
    "Changi Business Park Crescent",
    "Dover Crescent",
    "Eunos Link",
    "Farrer Road",
    "Geylang Bahru",
    "Havelock Road",
    "Jalan Membina",
    "Kallang Bahru",
    "Lorong Chuan",
    "Marine Parade Road",
    "Nanyang Crescent",
    "Orchard Boulevard",
)

# ---------------------------------------------------------------------------
# Interaction subjects, by category
# ---------------------------------------------------------------------------
SUBJECTS: Final[dict[Category, tuple[str, ...]]] = {
    Category.CLAIM_ISSUE: (
        "Claim submission failed",
        "Claim status enquiry",
        "Documents rejected on upload",
        "Chasing claim assessment",
        "Repeat claim upload attempt",
    ),
    Category.BILLING: (
        "Premium debited twice",
        "Payment method update",
        "Renewal invoice query",
        "Refund not received",
    ),
    Category.COVERAGE_QUERY: (
        "What does my policy cover",
        "Overseas coverage question",
        "Excess amount clarification",
        "Adding a named driver",
    ),
    Category.COMPLAINT: (
        "Unhappy with handling time",
        "Complaint about previous call",
        "Escalation request",
    ),
    Category.POLICY_CHANGE: (
        "Change of address",
        "Cancel auto-renewal",
        "Upgrade coverage tier",
        "Add dependant to policy",
    ),
    Category.TECHNICAL: (
        "Cannot log in to portal",
        "Mobile app upload error",
        "Document viewer not loading",
    ),
}

# ---------------------------------------------------------------------------
# Transcript fragments, by channel
# ---------------------------------------------------------------------------
OPENINGS: Final[dict[str, tuple[str, ...]]] = {
    "voice": (
        "Agent: Thanks for calling, you're speaking with {handler}. How can I help?",
        "Agent: Good afternoon, {handler} here. What can I do for you today?",
    ),
    "chat": (
        "Agent ({handler}): Hi there, how can I help today?",
        "Agent ({handler}): Hello — I can see your policy details. What's happened?",
    ),
    "email": (
        "From the customer: Hello, I am writing about the issue below.",
        "From the customer: Dear team, I need help with the following.",
    ),
    "callback": (
        "Agent: Hello, this is {handler} returning your call from earlier.",
        "Agent: Hi, {handler} here — you requested a callback about this.",
    ),
}

CUSTOMER_LINES: Final[dict[Category, tuple[str, ...]]] = {
    Category.CLAIM_ISSUE: (
        "Customer: I tried to submit my claim three times and it keeps failing.",
        "Customer: The website says my documents could not be read.",
        "Customer: I photographed the receipt but it will not go through.",
        "Customer: How long is the claim supposed to take? I submitted last week.",
    ),
    Category.BILLING: (
        "Customer: I have been charged twice this month.",
        "Customer: The renewal amount is higher than what I was quoted.",
        "Customer: I changed my card but the payment still failed.",
    ),
    Category.COVERAGE_QUERY: (
        "Customer: Does this cover me if I drive into Malaysia?",
        "Customer: What is my excess if I make a windscreen claim?",
        "Customer: I want to check whether physiotherapy is included.",
    ),
    Category.COMPLAINT: (
        "Customer: This is the third time I am calling about the same thing.",
        "Customer: Nobody has come back to me and it has been two weeks.",
        "Customer: I would like this escalated to a manager please.",
    ),
    Category.POLICY_CHANGE: (
        "Customer: I have moved, I need to update my address.",
        "Customer: Please stop the auto-renewal on this policy.",
        "Customer: I want to add my spouse as a named driver.",
    ),
    Category.TECHNICAL: (
        "Customer: The app crashes every time I attach a photo.",
        "Customer: I cannot log in — it keeps saying session expired.",
        "Customer: The document viewer just spins and never loads.",
    ),
}

AGENT_LINES: Final[tuple[str, ...]] = (
    "Agent: Let me pull that up — I can see the record now.",
    "Agent: I understand, and I am sorry that has been the experience.",
    "Agent: I have checked the details on our side and can explain what happened.",
    "Agent: Let me take you through the next step so this does not repeat.",
    "Agent: I have noted this on the account so the next colleague sees the history.",
)

RESOLUTIONS: Final[tuple[str, ...]] = (
    "Agent: I have raised this internally and you will hear back within two working days.",
    "Agent: That is now updated on your policy and the confirmation is on its way.",
    "Agent: I have logged a case so the specialist team can pick this up.",
    "Agent: We will re-run the submission on our side and confirm once it clears.",
    "Agent: Nothing further is needed from you at this point.",
)

CLOSINGS: Final[dict[str, tuple[str, ...]]] = {
    "voice": ("Agent: Anything else I can help with? Thanks for calling.",),
    "chat": ("Agent: Anything else before I close the chat?",),
    "email": ("Reply sent to the customer's registered email address.",),
    "callback": ("Agent: Thanks for your time — I will follow up as agreed.",),
}

# ---------------------------------------------------------------------------
# Knowledge base — docs/12 §3.5 requires every failure code to have an article
# ---------------------------------------------------------------------------
#: The planted article. ``search_kb("DOC_UNREADABLE")`` must reach this, and an
#: investigation that follows the evidence ends here (docs/12 §3.4).
PLANTED_ARTICLE_ID: Final = 31

KB_PLANTED_BODY: Final = """
Symptom
A claim reaches status submission_failed with failure code DOC_UNREADABLE. The
customer reports that the upload appeared to succeed, or that the portal returned a
generic error after the progress bar completed.

Cause
The document reached us but optical character recognition could not extract the
required fields. In order of frequency: a photograph taken at an angle so the edges
are cropped, a screen photographed rather than the document itself, resolution below
150 dpi, or a PDF that contains only a scanned image with no text layer.

Resolution
1. Confirm the claim is submission_failed and the code is DOC_UNREADABLE. A different
   code means a different article.
2. Ask the customer to re-capture the document flat, in daylight, with all four corners
   visible. Advise against photographing a screen.
3. Ask them to re-upload through the same channel. The claim reference does not change
   and no new claim should be created.
4. If a third attempt fails, raise a ticket to the Claims Document Support queue with
   the claim reference and the attempt count. Do not advise the customer to email the
   document, which bypasses validation and delays assessment.

Escalate when
The customer has made three or more attempts, the document is legible on inspection,
or the policy has a payment deadline within 48 hours.
""".strip()


class ArticleSpec:
    """One knowledge-base article, expanded into a body by the generator."""

    __slots__ = ("applies_to", "category", "cause", "escalate", "steps", "symptom", "title")

    def __init__(
        self,
        title: str,
        category: str,
        applies_to: tuple[FailureCode, ...],
        symptom: str,
        cause: str,
        steps: tuple[str, ...],
        escalate: str,
    ) -> None:
        self.title = title
        self.category = category
        self.applies_to = applies_to
        self.symptom = symptom
        self.cause = cause
        self.steps = steps
        self.escalate = escalate

    def render(self) -> str:
        numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(self.steps, start=1))
        return (
            f"Symptom\n{self.symptom}\n\n"
            f"Cause\n{self.cause}\n\n"
            f"Resolution\n{numbered}\n\n"
            f"Escalate when\n{self.escalate}"
        )


F = FailureCode

#: 39 generated articles plus the planted one. Every failure code appears at least
#: once; the two dominant codes appear more than once, matching the skewed distribution
#: the generator produces (docs/12 §3.5).
ARTICLES: Final[tuple[ArticleSpec, ...]] = (
    ArticleSpec(
        "Claim upload fails with DOC_MISSING",
        "claims",
        (F.DOC_MISSING,),
        "The claim is submission_failed and no document is attached to the submission.",
        "The upload was abandoned before completion, or the file exceeded the size limit "
        "and was discarded silently by an older mobile app build.",
        (
            "Confirm no document is attached to the claim reference.",
            "Ask the customer which file they attempted and its approximate size.",
            "Advise re-upload under 10 MB, one document per attachment.",
            "If the app version is older than the current release, advise updating first.",
        ),
        "The customer reports a successful upload but nothing is attached after two attempts.",
    ),
    ArticleSpec(
        "Reading the claim failure code",
        "claims",
        (F.DOC_MISSING, F.DOC_UNREADABLE, F.VALIDATION_ERROR),
        "A claim shows submission_failed and the agent needs to know which article applies.",
        "Every failed submission carries exactly one failure code, set by the validation "
        "service at the point of rejection.",
        (
            "Read the failure code from the claim record, not from the customer's description.",
            "Match the code to its article before advising anything.",
            "Record the code in any ticket you raise — the queue triages on it.",
        ),
        "The claim has no failure code but is marked failed; that is a platform defect.",
    ),
    ArticleSpec(
        "Policy lapsed at time of claim",
        "claims",
        (F.POLICY_LAPSED,),
        "Submission is rejected with POLICY_LAPSED though the customer believes they are covered.",
        "The incident date falls outside the policy's effective period, usually because a "
        "renewal payment failed and the grace period expired.",
        (
            "Compare the incident date against the policy effective_from and effective_to.",
            "Check whether a renewal payment failed in the same period.",
            "If the lapse was caused by a failed payment we did not notify, raise a billing case.",
            "Otherwise explain the coverage gap and the reinstatement options.",
        ),
        "The lapse followed a payment we failed to collect or notify on.",
    ),
    ArticleSpec(
        "Duplicate claim submissions",
        "claims",
        (F.DUPLICATE,),
        "A submission is rejected with DUPLICATE and the customer insists they submitted once.",
        "A retry after a timeout can create a second submission with the same incident date "
        "and amount, which the deduplication check rejects.",
        (
            "Locate the original claim by incident date and amount.",
            "Confirm the original is progressing; if so, no action is needed.",
            "Tell the customer the original reference so they stop retrying.",
            "If the original is also failed, resolve that failure instead.",
        ),
        "Both submissions are failed, or the amounts differ and both are legitimate.",
    ),
    ArticleSpec(
        "Validation errors on claim fields",
        "claims",
        (F.VALIDATION_ERROR,),
        "Submission is rejected with VALIDATION_ERROR and no document problem is reported.",
        "A required field is missing or inconsistent — most often an incident date in the "
        "future, or an amount exceeding the policy limit.",
        (
            "Read failure_detail, which names the offending field.",
            "Correct the field with the customer on the call where possible.",
            "Resubmit against the same claim reference.",
        ),
        "failure_detail is empty, or the field named is one the customer cannot edit.",
    ),
    ArticleSpec(
        "Gateway timeouts during submission",
        "claims",
        (F.GATEWAY_TIMEOUT,),
        "The submission times out and the claim is left in submission_failed.",
        "The upstream assessment gateway did not respond inside the window. This is a "
        "platform condition, not a customer error.",
        (
            "Check whether other claims failed in the same window before advising a retry.",
            "Ask the customer to retry once after fifteen minutes.",
            "If it fails again, raise a ticket to the Platform queue with the timestamps.",
        ),
        "More than one customer is affected in the same window.",
    ),
    ArticleSpec(
        "Claim amount exceeds the policy limit",
        "claims",
        (F.LIMIT_EXCEEDED,),
        "Submission is rejected with LIMIT_EXCEEDED.",
        "The claimed amount is above the remaining annual limit for the benefit, often "
        "because earlier claims in the same policy year consumed it.",
        (
            "Show the customer the remaining limit and the claims that consumed it.",
            "Advise submitting for the amount within the limit.",
            "Explain that the balance cannot be carried into the next policy year.",
        ),
        "The customer disputes an earlier claim that consumed the limit.",
    ),
    ArticleSpec(
        "Re-uploading documents without creating a new claim",
        "claims",
        (F.DOC_UNREADABLE, F.DOC_MISSING),
        "The customer has created several claims for one incident while retrying an upload.",
        "The portal offers a new claim rather than a retry when the previous attempt failed, "
        "so customers create duplicates in good faith.",
        (
            "Identify the earliest claim for the incident and keep it.",
            "Withdraw the duplicates so the assessment queue is not double-counted.",
            "Attach the readable document to the retained claim.",
        ),
        "Assessment has already started on more than one of the duplicates.",
    ),
    ArticleSpec(
        "Premium debited twice",
        "billing",
        (),
        "The customer sees two identical debits in the same billing period.",
        "A retry after a failed authorisation can settle both the original and the retry.",
        (
            "Confirm both debits share the same policy and amount.",
            "Raise a billing case with both transaction references.",
            "Advise a refund window of five working days.",
        ),
        "The duplicate is older than 30 days or spans two billing periods.",
    ),
    ArticleSpec(
        "Renewal price higher than quoted",
        "billing",
        (),
        "The renewal invoice does not match the quoted premium.",
        "Quotes are indicative until underwriting completes; a claim or a change of "
        "declared use during the year can move the final figure.",
        (
            "Compare the quote date against the renewal calculation date.",
            "Identify which factor changed and explain it plainly.",
            "Offer the coverage options that bring the premium back within budget.",
        ),
        "The difference exceeds 25 percent with no recorded change.",
    ),
    ArticleSpec(
        "Refund has not arrived",
        "billing",
        (),
        "A refund was approved but the customer has not received it.",
        "Refunds return to the original payment instrument, which may have been replaced "
        "since the payment was taken.",
        (
            "Confirm the refund was issued and to which instrument.",
            "Check whether the card on file has changed since.",
            "If it has, raise a billing case to reissue to the current instrument.",
        ),
        "The refund was issued more than ten working days ago.",
    ),
    ArticleSpec(
        "Payment method update fails",
        "billing",
        (),
        "The customer cannot save a new card.",
        "Address verification fails when the billing address on the card does not match "
        "the policy address.",
        (
            "Ask the customer to confirm the billing address held by their bank.",
            "Update the policy address first if it is genuinely out of date.",
            "Retry the card save after the address matches.",
        ),
        "The address matches and the save still fails.",
    ),
    ArticleSpec(
        "Overseas driving coverage",
        "coverage",
        (),
        "The customer asks whether a motor policy covers driving outside Singapore.",
        "Standard motor cover extends to West Malaysia and Thailand within a stated "
        "distance of the border; anything further needs an extension.",
        (
            "Confirm the destination and the travel dates.",
            "Check whether the extension is already on the policy.",
            "Add the extension before travel if it is not.",
        ),
        "Travel begins within 24 hours and the extension is not yet active.",
    ),
    ArticleSpec(
        "Explaining the excess",
        "coverage",
        (),
        "The customer disputes the excess deducted from a settlement.",
        "The excess is the fixed contribution stated on the schedule, and a separate "
        "young-driver excess can apply on top of it.",
        (
            "Read the excess figures from the policy schedule.",
            "Show how each applies to the settlement.",
            "Explain that a no-claim discount does not remove the excess.",
        ),
        "The excess applied does not match the schedule.",
    ),
    ArticleSpec(
        "Physiotherapy and allied health cover",
        "coverage",
        (),
        "The customer asks whether physiotherapy is included.",
        "Allied health is covered when referred by a registered practitioner and within "
        "the annual sub-limit.",
        (
            "Confirm a referral exists.",
            "Check the remaining sub-limit for the policy year.",
            "Explain the claim path and required documents.",
        ),
        "The referral is from an unrecognised practitioner.",
    ),
    ArticleSpec(
        "Adding a named driver",
        "policy",
        (),
        "The customer wants another driver added.",
        "Named drivers change the risk profile and therefore the premium; the change takes "
        "effect from the date it is accepted, not the date it is requested.",
        (
            "Collect the driver's licence details and years held.",
            "Quote the revised premium before confirming.",
            "Confirm the effective date with the customer.",
        ),
        "The additional driver has a recent at-fault claim.",
    ),
    ArticleSpec(
        "Change of address on a policy",
        "policy",
        (),
        "The customer has moved.",
        "For motor policies the address affects the premium, because it determines where "
        "the vehicle is kept overnight.",
        (
            "Update the address and confirm the effective date.",
            "Re-rate motor policies and explain any change.",
            "Confirm correspondence preferences are unchanged.",
        ),
        "The re-rated premium increases by more than 20 percent.",
    ),
    ArticleSpec(
        "Cancelling auto-renewal",
        "policy",
        (),
        "The customer wants to stop the policy renewing.",
        "Auto-renewal is cancelled separately from the policy itself; stopping one does "
        "not cancel the other.",
        (
            "Confirm whether the customer wants to stop renewal or cancel immediately.",
            "Apply the change and state the date cover ends.",
            "Send written confirmation.",
        ),
        "The customer wants immediate cancellation with a refund mid-term.",
    ),
    ArticleSpec(
        "Adding a dependant",
        "policy",
        (),
        "The customer wants a dependant added to a health policy.",
        "Dependants can be added at renewal, or mid-term following a qualifying life event.",
        (
            "Establish whether a qualifying event applies.",
            "Collect the dependant's details and any health declarations.",
            "Confirm when cover for the dependant begins.",
        ),
        "The dependant has a pre-existing condition requiring underwriting.",
    ),
    ArticleSpec(
        "Portal login fails with session expired",
        "technical",
        (),
        "The customer cannot log in; the portal returns session expired immediately.",
        "A stale session cookie from a previous release is rejected by the current "
        "authentication service.",
        (
            "Ask the customer to clear site data for the portal domain.",
            "Have them log in again in a private window to confirm.",
            "If it persists, capture the browser and version and raise a ticket.",
        ),
        "The failure reproduces in a private window on a supported browser.",
    ),
    ArticleSpec(
        "Mobile app crashes when attaching a photo",
        "technical",
        (F.DOC_MISSING,),
        "The app closes when the customer attaches a photograph to a claim.",
        "Older builds crash on images above a certain resolution when photo library "
        "permission was granted only for selected photos.",
        (
            "Confirm the app version and the device OS version.",
            "Ask the customer to grant full photo library access, or upload via the portal.",
            "Raise a ticket with the version details if it reproduces on the current build.",
        ),
        "The crash reproduces on the current app build.",
    ),
    ArticleSpec(
        "Document viewer does not load",
        "technical",
        (),
        "Documents on the portal never finish loading.",
        "A corporate network or content blocker is preventing the viewer's worker script "
        "from loading.",
        (
            "Ask the customer to try on a different network.",
            "Offer to email the document as an alternative.",
            "Record the network conditions if it must be escalated.",
        ),
        "The viewer fails on a home network with no blocker.",
    ),
    ArticleSpec(
        "Handling a repeat caller",
        "service",
        (),
        "The customer states this is their third contact about the same issue.",
        "Repeat contact usually means the previous case is open but stalled, not that "
        "nothing was done.",
        (
            "Read the case history before responding, and say what you can see.",
            "Do not open a second case for the same problem.",
            "Give a specific next step with a date, not a general reassurance.",
        ),
        "The case has been open beyond its target and has no owner.",
    ),
    ArticleSpec(
        "When to raise a ticket rather than answer",
        "service",
        (),
        "The agent can explain the problem but cannot resolve it on the contact.",
        "Tickets exist for work that leaves the conversation; answering in the moment is "
        "better whenever it is possible.",
        (
            "Resolve on the contact if you have the information and the authority.",
            "Raise a ticket when another team must act, and say so to the customer.",
            "Include the evidence you gathered so the queue does not repeat your work.",
        ),
        "The work needs an approval you do not hold.",
    ),
    ArticleSpec(
        "Escalation criteria",
        "service",
        (),
        "The customer asks for a manager, or the case meets an escalation trigger.",
        "Escalation moves ownership; it is not a way to acknowledge frustration.",
        (
            "Confirm the trigger: time in queue, repeat contact, or a regulatory deadline.",
            "Summarise what has already been attempted.",
            "Name the receiving team and what you are asking them to decide.",
        ),
        "A regulatory or contractual deadline is within 48 hours.",
    ),
    ArticleSpec(
        "Recording interaction outcomes",
        "service",
        (),
        "The next agent needs to understand what happened without replaying the call.",
        "The summary is what later contacts and this assistant read; the transcript is "
        "rarely opened.",
        (
            "Write the summary for someone who was not there.",
            "State the outcome and the next step, not the conversation.",
            "Name any reference you created.",
        ),
        "Never — this is part of every contact.",
    ),
    ArticleSpec(
        "Verifying a caller's identity",
        "service",
        (),
        "Before discussing policy details on an inbound call.",
        "Identity verification protects the customer, and is required before any policy "
        "detail is disclosed.",
        (
            "Confirm name, date of birth, and one policy detail.",
            "Do not disclose details the caller has not already stated correctly.",
            "If verification fails, offer to call back on the registered number.",
        ),
        "The caller is a third party acting on the customer's behalf.",
    ),
    ArticleSpec(
        "Claim assessment timelines",
        "claims",
        (),
        "The customer asks how long assessment will take.",
        "Assessment begins when a complete submission is received, not when the claim is "
        "first created.",
        (
            "Confirm the submission is complete and not in a failed state.",
            "Give the standard window from the date of successful submission.",
            "Set a follow-up if the claim is already beyond the window.",
        ),
        "The claim is beyond the published window with no assessment activity.",
    ),
    ArticleSpec(
        "What counts as a readable document",
        "claims",
        (F.DOC_UNREADABLE,),
        "The agent needs to advise the customer what will pass validation.",
        "Validation extracts text; anything that defeats extraction fails regardless of "
        "how readable it looks to a person.",
        (
            "All four corners visible, document flat, no glare.",
            "Photograph the document, never a screen showing the document.",
            "PDFs must contain a text layer, not only a scanned image.",
        ),
        "A document meeting all three still fails.",
    ),
    ArticleSpec(
        "Withdrawing a claim",
        "claims",
        (F.DUPLICATE,),
        "A claim needs to be removed from the queue.",
        "Withdrawal is reversible only before assessment begins.",
        (
            "Confirm with the customer which reference is being withdrawn.",
            "Check assessment has not started.",
            "Withdraw and confirm in writing.",
        ),
        "Assessment has already begun.",
    ),
    # index 31 — the planted article; body is supplied verbatim by the generator
    ArticleSpec(
        "Resolving DOC_UNREADABLE claim upload failures",
        "claims",
        (F.DOC_UNREADABLE,),
        "placeholder",
        "placeholder",
        ("placeholder",),
        "placeholder",
    ),
    ArticleSpec(
        "Claims made close to policy expiry",
        "claims",
        (F.POLICY_LAPSED,),
        "The incident date is within days of the policy end date.",
        "Cover is determined by the incident date, not the submission date, so a late "
        "submission on an in-force policy is still valid.",
        (
            "Establish the incident date precisely.",
            "Confirm the policy was in force on that date.",
            "Proceed normally if it was, regardless of when the claim was submitted.",
        ),
        "The incident date is disputed.",
    ),
    ArticleSpec(
        "Third-party claims against our customer",
        "claims",
        (),
        "A third party contacts us about our customer's policy.",
        "Third parties have a legitimate route but cannot be given policy detail.",
        (
            "Take the third party's details and the incident reference.",
            "Do not disclose policy terms or the customer's details.",
            "Route to the liability team.",
        ),
        "The third party states a legal deadline.",
    ),
    ArticleSpec(
        "Multiple failed submissions on one claim",
        "claims",
        (F.DOC_UNREADABLE, F.GATEWAY_TIMEOUT),
        "The same claim has failed submission more than twice.",
        "Repeated failure of one claim usually means the advice given after the first "
        "failure did not address the actual code.",
        (
            "Read the code on each attempt; they may differ.",
            "Address the most recent code, not the first.",
            "Raise a ticket after the third attempt rather than advising a fourth.",
        ),
        "Three or more attempts have failed.",
    ),
    ArticleSpec(
        "Explaining a rejected claim",
        "claims",
        (),
        "The claim was assessed and rejected, not failed at submission.",
        "Rejection is an assessment outcome and has a stated reason; it is not the same "
        "as a submission failure and has a different appeal route.",
        (
            "Distinguish clearly between rejected and submission_failed for the customer.",
            "Read the rejection reason and explain it without paraphrasing it away.",
            "Explain the appeal route and its deadline.",
        ),
        "The customer disputes the assessment basis.",
    ),
    ArticleSpec(
        "Sending documents by email",
        "claims",
        (F.DOC_MISSING,),
        "The customer asks whether they can email documents instead.",
        "Emailed documents bypass validation and are attached manually, which adds days.",
        (
            "Prefer the upload path in every case where it works.",
            "Use email only where an accessibility need makes upload impractical.",
            "If email is used, attach to the claim the same day.",
        ),
        "The customer has an accessibility need that upload does not accommodate.",
    ),
    ArticleSpec(
        "Reading a policy schedule",
        "coverage",
        (),
        "The agent needs to answer a coverage question accurately.",
        "The schedule is authoritative; product marketing pages are not.",
        (
            "Read the benefit, the limit, and the excess from the schedule.",
            "Check for endorsements, which override the standard wording.",
            "Quote the schedule wording rather than summarising it loosely.",
        ),
        "The schedule and an endorsement appear to contradict each other.",
    ),
    ArticleSpec(
        "No-claim discount questions",
        "coverage",
        (),
        "The customer asks how a claim affects their discount.",
        "The discount steps back by a fixed number of years on an at-fault claim and is "
        "unaffected by a successful recovery from a third party.",
        (
            "Establish whether the claim was at fault.",
            "Show the current and post-claim discount level.",
            "Mention protection options at renewal if available.",
        ),
        "The at-fault determination is disputed.",
    ),
    ArticleSpec(
        "Complaints that mention a regulator",
        "service",
        (),
        "The customer references an ombudsman or regulator.",
        "These contacts carry deadlines and must be routed, not handled on the contact.",
        (
            "Record the customer's words accurately.",
            "Do not offer a settlement or an opinion on the merits.",
            "Route to the complaints team the same day.",
        ),
        "Always — this cannot be closed on the contact.",
    ),
    ArticleSpec(
        "Vulnerable customer handling",
        "service",
        (),
        "The customer discloses a circumstance that affects their ability to engage.",
        "Disclosures are recorded so the customer does not have to repeat them.",
        (
            "Record the disclosure factually on the account.",
            "Offer the adjustments available and let the customer choose.",
            "Do not require the customer to re-explain on a later contact.",
        ),
        "The circumstance requires a specialist team.",
    ),
)
