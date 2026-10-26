"""내장 작성 템플릿 데이터 모음."""

from .contract_draft import TEMPLATE as CONTRACT_DRAFT
from .insurance_terms_draft import TEMPLATE as INSURANCE_TERMS_DRAFT
from .rfp_response_proposal import TEMPLATE as RFP_RESPONSE_PROPOSAL

BUILTIN_TEMPLATES = (RFP_RESPONSE_PROPOSAL, INSURANCE_TERMS_DRAFT, CONTRACT_DRAFT)
