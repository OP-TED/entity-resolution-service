from typing import Annotated

from fastapi import APIRouter, Depends

from ers.curation.domain.data_transfer_objects import EntityTypeDescriptor
from ers.curation.entrypoints.api.auth import VerifiedUser
from ers.curation.entrypoints.api.dependencies import get_rdf_config
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

router = APIRouter(prefix="/curation/entity-types", tags=["Entity Types"])


@router.get("")
async def list_entity_types(
    _user: VerifiedUser,
    rdf_config: Annotated[RDFMappingConfig, Depends(get_rdf_config)],
) -> list[EntityTypeDescriptor]:
    """Return the configured entity types and their UI display-name field."""
    return [
        EntityTypeDescriptor(name=name, display_name_field=cfg.display_name_field)
        for name, cfg in sorted(rdf_config.entity_types.items())
    ]
