# Module name: mappers/schema_yaml_json.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Description: This module provides a lightweight utility for transforming and validating
dataframes using YAML-defined mappings and JSON schema validation within
the Wattleflow framework. It enables flexible conversion of YAML
configurations into column mappings and validation schemas, streamlining
data transformation and integrity checks.


class MapperSchemaYAML2JSON
    def __init__(self, mapper: ColumnMapper, validator: SchemaValidator):

    @classmethod
    def from_yaml(cls, cfg_str: str):
    def transform(self, df: pd.DataFrame) -> pd.DataFrame

Usage:
    yaml_cfg ='''
    mapping:
        name: name
        age: years
        json_schema:
            type: object
    properties:
        name:
            type: string
        age:
            type: integer
    required: [name, age]
    '''

With dataframe

df = pd.DataFrame({
    "name": ["Ann", "Brian"],
    "age": [30, 40]
})

# Create facade from YAML
mapper_validator = MapperSchemaYAML2JSON.from_yaml(yaml_cfg)

# Transform: mapping + validation
df_out = mapper_validator.transform(df)

print(df_out)

"""

import yaml
import jsonschema
import pandas as pd


class ColumnMapper:
    def __init__(self, mapping: dict):
        self.mapping = mapping

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(columns=self.mapping)


class SchemaValidator:
    def __init__(self, schema: dict):
        self.schema = schema

    def validate_row(self, row: dict):
        jsonschema.validate(instance=row, schema=self.schema)


class MapperSchemaYAML2JSON:  # Facade
    def __init__(self, mapper: ColumnMapper, validator: SchemaValidator):
        self.mapper = mapper
        self.validator = validator

    @classmethod
    def from_yaml(cls, cfg_str: str):
        cfg = yaml.safe_load(cfg_str)
        return cls(ColumnMapper(cfg["mapping"]), SchemaValidator(cfg["json_schema"]))

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df2 = self.mapper.apply(df)
        for rec in df2.to_dict(orient="records"):
            self.validator.validate_row(rec)
        return df2
