import unittest

from axiom_rift import __version__


class ImportTest(unittest.TestCase):
    def test_version_is_defined(self) -> None:
        self.assertTrue(__version__)


if __name__ == "__main__":
    unittest.main()
