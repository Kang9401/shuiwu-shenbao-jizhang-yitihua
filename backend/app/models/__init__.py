from app.models.accounting import (
    CertificationLedger,
    InvoiceLedger,
    OrganizationMapping,
    PersonnelMasterArtifact,
    PersonnelMasterImportBatch,
    ReconciliationImportBatch,
    ReconciliationImportRow,
    VoucherDraft,
)
from app.models.core import Artifact, Company, Job, Period, UploadedFile
from app.models.tax import TaxMonthlyArtifact, VerificationRound, VerificationSession
from app.models.pit_reconciliation import (
    PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail,
    PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck,
)


COMPANY_SCOPED_MODELS = (
    Period,
    UploadedFile,
    Job,
    Artifact,
    InvoiceLedger,
    CertificationLedger,
    VoucherDraft,
    PersonnelMasterArtifact,
    PersonnelMasterImportBatch,
    ReconciliationImportBatch,
    ReconciliationImportRow,
    OrganizationMapping,
    VerificationSession,
    VerificationRound,
    TaxMonthlyArtifact,
    PitReconciliationWorkpaper,
    PitReconciliationSource,
    PitDeclarationSummary,
    PitTaxAmountCheck,
    PitOccurrenceCheck,
    PitReconciliationOrgSummary,
    PitReconciliationDifferenceDetail,
    PitBankTaxMatch,
)

__all__ = [model.__name__ for model in (*COMPANY_SCOPED_MODELS, Company)]
