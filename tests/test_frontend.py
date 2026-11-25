from .base import TatcTestCase


class FrontendTestCase(TatcTestCase):
    def test_revalidate_files(self):
        # browsers revalidate files of the frontend before each use
        for path in ("/", "/styles.css", "/index.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            # files not modified are not sent again
            revalidated = self.client.get(
                path, headers={"If-None-Match": response.headers["ETag"]}
            )
            self.assertEqual(revalidated.status_code, 304)
            self.assertEqual(revalidated.content, b"")
            self.assertEqual(revalidated.headers["Cache-Control"], "no-cache")
