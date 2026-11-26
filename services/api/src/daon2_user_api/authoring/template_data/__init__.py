"""내장 작성 템플릿 데이터 모음."""

from .contract_draft import TEMPLATE as CONTRACT_DRAFT
from .general_document import TEMPLATE as GENERAL_DOCUMENT
from .insurance_terms_draft import TEMPLATE as INSURANCE_TERMS_DRAFT
from .rfp_response_proposal import TEMPLATE as RFP_RESPONSE_PROPOSAL
from .reference_proposal_draft import TEMPLATE as REFERENCE_PROPOSAL_DRAFT

BUILTIN_TEMPLATES = (RFP_RESPONSE_PROPOSAL, INSURANCE_TERMS_DRAFT, CONTRACT_DRAFT, GENERAL_DOCUMENT, REFERENCE_PROPOSAL_DRAFT)
