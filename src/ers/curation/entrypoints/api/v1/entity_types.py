from typing import Annotated

from fastapi import APIRouter, Depends

from ers.curation.entrypoints.api.auth import VerifiedUser
from ers.curation.entrypoints.api.dependencies import get_rdf_config
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

router = APIRouter(prefix="/curation/entity-types", tags=["Entity Types"])


@router.get("")
async def list_entity_types(
    _user: VerifiedUser,
    rdf_config: Annotated[RDFMappingConfig, Depends(get_rdf_config)],
) -> list[str]:
    """Return the list of configured entity types."""
    return sorted(rdf_config.entity_types.keys())
