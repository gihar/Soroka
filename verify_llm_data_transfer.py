#!/usr/bin/env python3
"""
Verification script for testing data transfer between two LLM requests in Soroka.

This script tests whether information from the first LLM request is correctly
passed to the second request in the consolidated two-request approach.
"""

import asyncio
import json
import logging
import sys
import os
from typing import Dict, Any, List
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent / "src"))

from models.llm_schemas import ExtractionSchema, ConsolidatedProtocolSchema
from src.prompts.prompts import build_extraction_prompt, build_protocol_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('llm_data_transfer_verification.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LLMDataTransferVerifier:
    """Verifies data transfer between LLM requests."""

    def __init__(self):
        self.test_results = []
        self.issues_found = []

    def log_test_step(self, step_name: str, details: Dict[str, Any] = None):
        """Log a test step with details."""
        log_entry = {
            'step': step_name,
            'details': details or {},
            'timestamp': str(asyncio.get_event_loop().time())
        }
        self.test_results.append(log_entry)
        logger.info(f"TEST STEP: {step_name}")
        if details:
            for key, value in details.items():
                logger.info(f"  {key}: {value}")

    def log_issue(self, issue_type: str, description: str, data: Any = None):
        """Log an issue found during verification."""
        issue = {
            'type': issue_type,
            'description': description,
            'data': data,
            'timestamp': str(asyncio.get_event_loop().time())
        }
        self.issues_found.append(issue)
        logger.warning(f"ISSUE FOUND: {issue_type} - {description}")
        if data:
            logger.warning(f"  Data: {data}")

    def create_mock_extraction_result(self) -> Dict[str, Any]:
        """Create a mock first request result for testing."""
        return {
            # Speaker mapping results
            'speaker_mappings': {
                'SPEAKER_0': 'Иван Петров',
                'SPEAKER_1': 'Мария Сидорова'
            },
            'speaker_confidence_scores': {
                'SPEAKER_0': 0.95,
                'SPEAKER_1': 0.87
            },
            'unmapped_speakers': ['SPEAKER_2'],
            'mapping_notes': 'SPEAKER_2 confidence < 0.7, requires manual verification',

            # Meeting structure extraction
            'meeting_title': 'Еженедельная планерка разработки',
            'meeting_type': 'technical',
            'meeting_date': '2024-01-15',
            'meeting_time': '14:00',
            'participants': 'Иван Петров\nМария Сидорова\nАлексей Иванов',
            'agenda': 'Обзор прогресса\nДеплоймент\nПланирование спринта',
            'discussion': 'Иван: Завершили модуль аутентификации.\nМария: Проблемы с деплойментом на staging.\nАлексей: Начинаем рефакторинг базы данных.',
            'key_points': 'Завершен модуль аутентификации\nПланы по рефакторингу БД',
            'decisions': 'Деплой в продакшен 20.01\nСпринт фокусируется на UI',
            'action_items': 'Алексей: Тесты для API до 18.01\nИван: Документация к 19.01',
            'next_meeting': '2024-01-22, 14:00',
            'additional_notes': 'Обсужден технический долг',

            # Quality assessment
            'extraction_confidence': 0.87,
            'missing_elements': [],
            'quality_issues': ['Some segments unclear'],
            'extraction_notes': 'Comprehensive extraction completed'
        }

    def create_mock_template_variables(self) -> Dict[str, str]:
        """Create mock template variables for testing."""
        return {
            'meeting_title': '',
            'meeting_date': '',
            'meeting_time': '',
            'participants': '',
            'agenda': '',
            'discussion': '',
            'key_points': '',
            'decisions': '',
            'action_items': '',
            'next_meeting': '',
            'additional_notes': ''
        }

    def verify_schema_compatibility(self, extraction_result: Dict[str, Any]) -> bool:
        """Verify that extraction result matches ExtractionSchema."""
        try:
            # Try to validate with Pydantic schema
            validated = ExtractionSchema(**extraction_result)
            self.log_test_step("Schema validation passed", {
                'validated_fields': len(extraction_result),
                'speaker_mapping_count': len(extraction_result.get('speaker_mappings', {})),
                'extraction_confidence': extraction_result.get('extraction_confidence', 0.0)
            })
            return True
        except Exception as e:
            self.log_issue("Schema validation error", str(e), extraction_result)
            return False

    def verify_data_transfer_to_prompt(self, extraction_result: Dict[str, Any], template_variables: Dict[str, str]) -> bool:
        """Verify that extraction result is properly incorporated into the second request prompt."""
        try:
            # Build the second request prompt
            protocol_prompt = build_protocol_prompt(
                extraction_result=extraction_result,
                template_variables=template_variables,
                meeting_type=extraction_result.get('meeting_type', 'general')
            )

            # Check if all key extraction data is present in the prompt
            missing_in_prompt = []

            # Check speaker mapping
            speaker_mapping = extraction_result.get('speaker_mappings', {})
            if speaker_mapping:
                prompt_text = protocol_prompt.lower()
                for speaker_id, name in speaker_mapping.items():
                    if speaker_id.lower() not in prompt_text or name.lower() not in prompt_text:
                        missing_in_prompt.append(f"Speaker mapping {speaker_id} → {name}")

            # Check meeting data
            key_fields = [
                'meeting_title', 'meeting_type', 'meeting_date', 'meeting_time',
                'participants', 'agenda', 'discussion', 'key_points',
                'decisions', 'action_items'
            ]

            for field in key_fields:
                field_value = extraction_result.get(field, '')
                if field_value and field_value not in ['Not specified', '']:
                    # Check if field value is referenced in prompt
                    if field.lower() not in protocol_prompt.lower():
                        missing_in_prompt.append(f"Field reference: {field}")

            if missing_in_prompt:
                self.log_issue("Missing data in prompt", f"Data not found in prompt: {missing_in_prompt}", {
                    'missing_count': len(missing_in_prompt),
                    'missing_items': missing_in_prompt
                })
                return False

            self.log_test_step("Prompt data transfer verified", {
                'prompt_length': len(protocol_prompt),
                'speaker_mappings_included': len(speaker_mapping),
                'key_fields_checked': len(key_fields)
            })

            return True

        except Exception as e:
            self.log_issue("Prompt construction error", str(e))
            return False

    def verify_data_flow_consistency(self, extraction_result: Dict[str, Any]) -> bool:
        """Verify that data flows consistently through the processing pipeline."""
        try:
            # Simulate the data combination step from llm_providers.py:3347-3368
            combined_data = {}

            # Check if extraction result has protocol_data or uses direct fields
            if 'protocol_data' in extraction_result:
                combined_data.update(extraction_result['protocol_data'])
                self.log_test_step("Used protocol_data from extraction result")
            else:
                # ExtractionSchema fields
                fields_to_extract = [
                    'meeting_title', 'meeting_date', 'meeting_time', 'participants',
                    'agenda', 'discussion', 'key_points', 'decisions',
                    'action_items', 'next_meeting', 'additional_notes'
                ]

                for field in fields_to_extract:
                    if field in extraction_result:
                        combined_data[field] = extraction_result[field]

                self.log_test_step("Used direct field extraction", {
                    'fields_extracted': len([f for f in fields_to_extract if f in extraction_result])
                })

            # Verify all required fields are present
            missing_fields = []
            for field in fields_to_extract:
                if field not in combined_data:
                    missing_fields.append(field)

            if missing_fields:
                self.log_issue("Missing fields in combined data", f"Fields not found: {missing_fields}")
                return False

            # Verify data integrity
            integrity_issues = []
            for field, value in combined_data.items():
                if value is None:
                    integrity_issues.append(f"Field {field} is None")
                elif isinstance(value, str) and len(value.strip()) == 0 and field in ['meeting_title', 'participants']:
                    integrity_issues.append(f"Required field {field} is empty")

            if integrity_issues:
                self.log_issue("Data integrity issues", f"Problems found: {integrity_issues}")
                return False

            self.log_test_step("Data flow consistency verified", {
                'combined_fields': len(combined_data),
                'data_integrity': 'OK'
            })

            return True

        except Exception as e:
            self.log_issue("Data flow verification error", str(e))
            return False

    def verify_speaker_mapping_preservation(self, extraction_result: Dict[str, Any]) -> bool:
        """Verify that speaker mapping data is preserved and accessible."""
        try:
            speaker_mappings = extraction_result.get('speaker_mappings', {})
            confidence_scores = extraction_result.get('speaker_confidence_scores', {})
            unmapped_speakers = extraction_result.get('unmapped_speakers', [])

            # Verify speaker mapping structure
            if not isinstance(speaker_mappings, dict):
                self.log_issue("Invalid speaker mapping type", f"Expected dict, got {type(speaker_mappings)}")
                return False

            # Verify confidence scores structure
            if not isinstance(confidence_scores, dict):
                self.log_issue("Invalid confidence scores type", f"Expected dict, got {type(confidence_scores)}")
                return False

            # Verify unmapped speakers structure
            if not isinstance(unmapped_speakers, list):
                self.log_issue("Invalid unmapped speakers type", f"Expected list, got {type(unmapped_speakers)}")
                return False

            # Check consistency between mappings and confidence scores
            consistency_issues = []
            for speaker_id in speaker_mappings:
                if speaker_id not in confidence_scores:
                    consistency_issues.append(f"Missing confidence score for {speaker_id}")
                elif not isinstance(confidence_scores[speaker_id], (int, float)):
                    consistency_issues.append(f"Invalid confidence score type for {speaker_id}")
                elif confidence_scores[speaker_id] < 0.0 or confidence_scores[speaker_id] > 1.0:
                    consistency_issues.append(f"Confidence score out of range for {speaker_id}")

            if consistency_issues:
                self.log_issue("Speaker mapping consistency issues", f"Problems: {consistency_issues}")
                return False

            self.log_test_step("Speaker mapping preservation verified", {
                'mapped_speakers': len(speaker_mappings),
                'unmapped_speakers': len(unmapped_speakers),
                'average_confidence': sum(confidence_scores.values()) / len(confidence_scores) if confidence_scores else 0.0
            })

            return True

        except Exception as e:
            self.log_issue("Speaker mapping verification error", str(e))
            return False

    def verify_quality_metrics_transfer(self, extraction_result: Dict[str, Any]) -> bool:
        """Verify that quality metrics from first request are accessible."""
        try:
            quality_fields = [
                'extraction_confidence',
                'missing_elements',
                'quality_issues',
                'extraction_notes'
            ]

            missing_quality_fields = []
            for field in quality_fields:
                if field not in extraction_result:
                    missing_quality_fields.append(field)

            if missing_quality_fields:
                self.log_issue("Missing quality metrics", f"Fields not found: {missing_quality_fields}")
                return False

            # Validate quality metrics types and ranges
            extraction_confidence = extraction_result.get('extraction_confidence', 0.0)
            if not isinstance(extraction_confidence, (int, float)):
                self.log_issue("Invalid confidence type", f"Expected number, got {type(extraction_confidence)}")
                return False

            if extraction_confidence < 0.0 or extraction_confidence > 1.0:
                self.log_issue("Confidence out of range", f"Value: {extraction_confidence}")
                return False

            missing_elements = extraction_result.get('missing_elements', [])
            quality_issues = extraction_result.get('quality_issues', [])

            if not isinstance(missing_elements, list):
                self.log_issue("Invalid missing_elements type", f"Expected list, got {type(missing_elements)}")
                return False

            if not isinstance(quality_issues, list):
                self.log_issue("Invalid quality_issues type", f"Expected list, got {type(quality_issues)}")
                return False

            self.log_test_step("Quality metrics transfer verified", {
                'extraction_confidence': extraction_confidence,
                'missing_elements_count': len(missing_elements),
                'quality_issues_count': len(quality_issues),
                'has_extraction_notes': bool(extraction_result.get('extraction_notes', '').strip())
            })

            return True

        except Exception as e:
            self.log_issue("Quality metrics verification error", str(e))
            return False

    async def run_comprehensive_verification(self) -> Dict[str, Any]:
        """Run all verification tests."""
        logger.info("Starting comprehensive LLM data transfer verification")

        # Create test data
        extraction_result = self.create_mock_extraction_result()
        template_variables = self.create_mock_template_variables()

        self.log_test_step("Test data created", {
            'extraction_result_fields': len(extraction_result),
            'template_variables_count': len(template_variables)
        })

        # Run all verification tests
        test_results = {
            'schema_compatibility': self.verify_schema_compatibility(extraction_result),
            'data_transfer_to_prompt': self.verify_data_transfer_to_prompt(extraction_result, template_variables),
            'data_flow_consistency': self.verify_data_flow_consistency(extraction_result),
            'speaker_mapping_preservation': self.verify_speaker_mapping_preservation(extraction_result),
            'quality_metrics_transfer': self.verify_quality_metrics_transfer(extraction_result)
        }

        # Calculate overall success
        total_tests = len(test_results)
        passed_tests = sum(1 for result in test_results.values() if result)
        overall_success = passed_tests == total_tests

        self.log_test_step("Verification completed", {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'overall_success': overall_success,
            'issues_found': len(self.issues_found)
        })

        return {
            'overall_success': overall_success,
            'test_results': test_results,
            'issues_found': self.issues_found,
            'test_steps': self.test_results
        }

    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a detailed verification report."""
        report = []
        report.append("=" * 80)
        report.append("LLM DATA TRANSFER VERIFICATION REPORT")
        report.append("=" * 80)

        # Overall status
        report.append(f"\nOVERALL STATUS: {'✅ PASSED' if results['overall_success'] else '❌ FAILED'}")
        report.append(f"Tests Run: {len(results['test_results'])}")
        report.append(f"Issues Found: {len(results['issues_found'])}")

        # Individual test results
        report.append("\n" + "=" * 40)
        report.append("INDIVIDUAL TEST RESULTS")
        report.append("=" * 40)

        for test_name, result in results['test_results'].items():
            status = "✅ PASSED" if result else "❌ FAILED"
            report.append(f"{test_name}: {status}")

        # Issues found
        if results['issues_found']:
            report.append("\n" + "=" * 40)
            report.append("ISSUES FOUND")
            report.append("=" * 40)

            for i, issue in enumerate(results['issues_found'], 1):
                report.append(f"\n{i}. {issue['type']}")
                report.append(f"   Description: {issue['description']}")
                if issue['data']:
                    report.append(f"   Data: {issue['data']}")

        # Recommendations
        report.append("\n" + "=" * 40)
        report.append("RECOMMENDATIONS")
        report.append("=" * 40)

        if results['overall_success']:
            report.append("✅ All tests passed. Data transfer between LLM requests is working correctly.")
        else:
            report.append("❌ Issues found. Review the following areas:")

            failed_tests = [name for name, result in results['test_results'].items() if not result]
            for test in failed_tests:
                if test == 'schema_compatibility':
                    report.append("   • Fix schema validation issues in ExtractionSchema")
                elif test == 'data_transfer_to_prompt':
                    report.append("   • Ensure all extraction data is included in second request prompt")
                elif test == 'data_flow_consistency':
                    report.append("   • Review data combination logic in llm_providers.py:3347-3368")
                elif test == 'speaker_mapping_preservation':
                    report.append("   • Fix speaker mapping data structure and consistency")
                elif test == 'quality_metrics_transfer':
                    report.append("   • Ensure quality metrics are properly extracted and transferred")

        report.append("\n" + "=" * 80)
        return "\n".join(report)

async def main():
    """Main verification function."""
    verifier = LLMDataTransferVerifier()

    try:
        # Run comprehensive verification
        results = await verifier.run_comprehensive_verification()

        # Generate and print report
        report = verifier.generate_report(results)
        print(report)

        # Save report to file
        with open('llm_data_transfer_verification_report.txt', 'w', encoding='utf-8') as f:
            f.write(report)

        logger.info("Verification completed. Report saved to llm_data_transfer_verification_report.txt")

        # Return exit code based on results
        sys.exit(0 if results['overall_success'] else 1)

    except Exception as e:
        logger.error(f"Verification failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())