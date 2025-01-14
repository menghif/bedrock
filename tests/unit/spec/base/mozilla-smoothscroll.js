/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

/* For reference read the Jasmine and Sinon docs
 * Jasmine docs: https://jasmine.github.io/2.3/introduction.html
 * Sinon docs: http://sinonjs.org/docs/
 */

describe('mozilla-smoothscroll.js', function () {
    'use strict';

    describe('Mozilla.smoothScroll scrolling', function () {
        it('should use window.scrollTo when native smooth scrolling is supported', function () {
            spyOn(window, 'scrollTo');

            Mozilla.smoothScroll({
                top: 200,
                unitTest: 'native'
            });

            expect(window.scrollTo).toHaveBeenCalledWith({
                behavior: 'smooth',
                top: 200,
                left: 0
            });
        });

        it('should use legacy window.scrollTo when smooth scrolling is not available', function () {
            spyOn(window, 'scrollTo');

            Mozilla.smoothScroll({
                top: 200,
                unitTest: 'fallback' // disable smoothScroll
            });

            expect(window.scrollTo).toHaveBeenCalledWith(200, 0);
        });
    });
});
