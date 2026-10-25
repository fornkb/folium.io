"""Aggregate only noisy reference-repair messages; preserve parser failures."""
import logging
import unittest
from concurrent.futures import ThreadPoolExecutor

from core import summarized_pdf_warnings


class PdfWarningTests(unittest.TestCase):
    def test_reference_repair_flood_is_grouped_and_other_warnings_remain(self):
        logger = logging.getLogger("pypdf._reader")
        with self.assertLogs(logger, level="WARNING") as logs:
            with summarized_pdf_warnings():
                for i in range(67):
                    logger.warning("Ignoring wrong pointing object %s 0 (offset 0)", i)
                logger.warning("Other PDF parsing warning")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(logger.warning, "Ignoring wrong pointing object 99 0 (offset 0)").result()
            logger.warning("Ignoring wrong pointing object 100 0 (offset 0)")
        self.assertEqual(4, len(logs.output))
        self.assertTrue(any("67 invalid object references" in line for line in logs.output))
        self.assertTrue(any("Other PDF parsing warning" in line for line in logs.output))
        self.assertTrue(any("object 99 " in line for line in logs.output))
        self.assertTrue(any("object 100 " in line for line in logs.output))

    def test_failed_parse_restores_logging_and_keeps_exception(self):
        logger = logging.getLogger("pypdf._reader")
        before = list(logger.filters)
        with self.assertLogs(logger, level="WARNING") as logs:
            with self.assertRaisesRegex(ValueError, "Unreadable PDF"):
                with summarized_pdf_warnings():
                    logger.warning("Ignoring wrong pointing object 8 0 (offset 0)")
                    raise ValueError("Unreadable PDF")
            logger.warning("Ignoring wrong pointing object 10 0 (offset 0)")
        self.assertEqual(before, logger.filters)
        self.assertEqual(2, len(logs.output))


if __name__ == "__main__":
    unittest.main()
